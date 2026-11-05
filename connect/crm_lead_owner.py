from urllib.parse import quote

import frappe
from frappe import _

from connect.crm_integration import connect_owner, crm_request, crm_settings, crm_user
from connect.partner.doctype.connect_partner_member.connect_partner_member import LEAD_ACCESS
from connect.permissions import _has_partner_access


def queue_lead_owner_sync(thread: str, partner: str, previous: str | None = None) -> None:
	"""Gives the thread's CRM Lead to its owner on Connect, in the background. A thread without
	a CRM Lead yet gets its owner when the Lead is made."""
	if not frappe.db.get_value("Connect Thread", thread, "crm_lead_id") or not crm_settings(partner):
		return
	frappe.enqueue(
		"connect.crm_lead_owner.sync_lead_owner",
		queue="short",
		enqueue_after_commit=True,
		thread=thread,
		previous=previous,
	)


def queue_consultant_owner_sync(doc, method=None):
	"""on_update on Connect Thread: a new Starter Pack consultant takes over the Lead."""
	if doc.has_value_changed("consultant"):
		before = doc.get_doc_before_save()
		queue_lead_owner_sync(doc.name, doc.partner, before and before.consultant)


def sync_lead_owner(thread: str, previous: str | None = None) -> None:
	"""Background job: makes the thread's owner on Connect the owner of its CRM Lead, which
	assigns it to them, and takes it off whoever had it before."""
	thread_doc = frappe.get_doc("Connect Thread", thread)
	settings = crm_settings(thread_doc.partner)
	user = connect_owner(thread_doc)
	if not settings or not thread_doc.crm_lead_id or not user:
		return

	try:
		owner = crm_user(settings, user)
		if not owner:
			# The Lead stays with whoever has it, for the sales team to reassign by hand.
			thread_doc.db_set(
				"crm_sync_error",
				_("The Lead's owner wasn't changed: {0} has no user on the CRM.").format(user),
				update_modified=False,
			)
			return

		path = f"/api/resource/CRM Lead/{quote(thread_doc.crm_lead_id)}"
		crm_request(settings, "PUT", path, json={"lead_owner": owner})
		_unassign(settings, thread_doc.crm_lead_id, crm_user(settings, previous), owner)
	except Exception:
		frappe.log_error(title=f"CRM Lead owner change failed for Connect Thread {thread}")


def _unassign(settings, crm_lead: str, before: str | None, owner: str) -> None:
	if before and before != owner:
		crm_request(
			settings,
			"POST",
			"/api/method/frappe.desk.form.assign_to.remove",
			json={"doctype": "CRM Lead", "name": crm_lead, "assign_to": before},
		)


def owner_webhook(partner: str, integration_user: str, secret: str) -> dict:
	"""The Webhook that tells Connect when someone on the partner's CRM gives a Lead to someone
	else. Changes Connect itself made as its API user are left out, so they don't come back."""
	callback_url = frappe.utils.get_url(
		f"/api/method/connect.api.crm_webhook.receive_crm_lead_owner?partner={quote(partner)}"
	)
	return {
		"name": f"Connect Owner Sync - {partner}",
		"webhook_doctype": "CRM Lead",
		# on_change runs only for a saved Lead's changes, never when one is made.
		"webhook_docevent": "on_change",
		"condition": f"doc.has_value_changed('lead_owner') and doc.modified_by!={integration_user!r}",
		"request_url": callback_url,
		"request_method": "POST",
		"request_structure": "Form URL-Encoded",
		"webhook_data": [{"fieldname": f, "key": f} for f in ("name", "lead_owner")],
		"webhook_headers": [{"key": "Content-Type", "value": "application/json"}],
		"enable_security": 1,
		"webhook_secret": secret,
		"enabled": 1,
	}


def record_crm_lead_owner(partner: str, crm_lead: str | None, crm_owner: str | None) -> None:
	"""A Lead was given to someone else on the partner's CRM. On Connect the lead goes to the
	same person when they take leads on the team; otherwise it notes who has it on the CRM."""
	thread = crm_lead and frappe.db.get_value("Connect Thread", {"partner": partner, "crm_lead_id": crm_lead}, "name")
	lead = thread and frappe.db.get_value("Partner Lead", {"thread": thread}, "name")
	if not lead or not crm_owner:
		return  # not a Connect lead, or unassigned on the CRM: Connect keeps its owner

	doc = frappe.get_doc("Partner Lead", lead)
	before = (doc.assigned_to, doc.crm_owner)
	user = member_for_crm_user(partner, crm_owner)
	if user and _has_partner_access(partner, user, LEAD_ACCESS):
		doc.assigned_to = user
		doc.crm_owner = None
	else:
		doc.crm_owner = crm_owner
	if (doc.assigned_to, doc.crm_owner) == before:
		return
	doc.flags.from_crm = True
	# The CRM's signed webhook, with no Connect login; the partner's own CRM decided this.
	doc.save(ignore_permissions=True, ignore_version=False)


def member_for_crm_user(partner: str, crm_owner: str) -> str | None:
	"""The team member who is this CRM user: linked to it, else with the same email."""
	linked = frappe.db.get_value(
		"Connect Partner Member", {"partner": partner, "crm_user": crm_owner, "is_removed": 0}, "user"
	)
	if linked:
		return linked
	Member = frappe.qb.DocType("Connect Partner Member")
	User = frappe.qb.DocType("User")
	rows = (
		frappe.qb.from_(Member)
		.join(User)
		.on(User.name == Member.user)
		.select(Member.user)
		.where((Member.partner == partner) & (Member.is_removed == 0) & (User.email == crm_owner))
		.limit(1)
		.run(pluck=True)
	)
	return rows[0] if rows else None


@frappe.whitelist(methods=["POST"])
def match_crm_team(partner: str) -> int:
	"""Desk: links the partner's team to their CRM users again. Returns how many are on the CRM."""
	frappe.only_for("System Manager")
	if not crm_settings(partner):
		frappe.throw(_("Turn on CRM sync for this partner first."))
	return match_team(partner)


def queue_team_match(doc, method=None):
	"""on_update on Partner CRM Settings: links the team to the CRM's users once sync is on."""
	if doc.enabled:
		frappe.enqueue("connect.crm_lead_owner.match_team", queue="short", enqueue_after_commit=True, partner=doc.partner)


def queue_member_match(doc, method=None):
	"""on_update on Connect Partner Member: someone joining (or back on) the team is looked up
	on the CRM, so they're offered as on it or not."""
	# A new row counts as changed too.
	joined = doc.has_value_changed("is_removed") or doc.has_value_changed("user")
	if joined and not doc.is_removed and crm_settings(doc.partner):
		frappe.enqueue("connect.crm_lead_owner.match_team", queue="short", enqueue_after_commit=True, partner=doc.partner)


def match_team(partner: str) -> int:
	"""Links each team member to their CRM user by email. A link to a user still on the CRM is
	kept, as the partner may have set it by hand. Returns how many are on the CRM."""
	settings = crm_settings(partner)
	if not settings:
		return 0
	crm_users = _crm_users(settings)
	members = frappe.get_all(
		"Connect Partner Member",
		filters={"partner": partner, "is_removed": 0},
		fields=["name", "user", "crm_user", "user.email as email"],
	)
	for member in members:
		linked = member.crm_user if member.crm_user in crm_users.values() else crm_users.get(member.email)
		if linked != member.crm_user:
			frappe.db.set_value("Connect Partner Member", member.name, "crm_user", linked)
	return frappe.db.count("Connect Partner Member", {"partner": partner, "is_removed": 0, "crm_user": ["is", "set"]})


def _crm_users(settings) -> dict[str, str]:
	"""The CRM's enabled users, by email."""
	rows = crm_request(
		settings,
		"GET",
		"/api/resource/User",
		params={
			"filters": frappe.as_json([["enabled", "=", 1]]),
			"fields": frappe.as_json(["name", "email"]),
			"limit_page_length": 0,
		},
	).json()["data"]
	return {row["email"]: row["name"] for row in rows if row.get("email")}


def set_up_owner_sync(partner: str) -> None:
	"""Background job: a partner connected before Lead owners synced gets the owner webhook on
	their CRM, and their team linked to its users."""
	from connect.crm_integration import set_up_reply_webhook

	set_up_reply_webhook(frappe.get_doc("Partner CRM Settings", partner))
	match_team(partner)
