"""Partners' leads, sent to Frappe's CRM for the sales team.

Each customer a partner is working is one Lead on Frappe's CRM, and each partner working them is a
note on it, kept up to date as the partner's lead moves. Frappe's own leads (its Starter Pack chats)
are left out: they reach the same CRM through the chat sync (connect.crm_integration).
"""

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import escape_html, fmt_money
from frappe.utils.synchronization import filelock

from connect.crm_enquiries import frappe_crm
from connect.crm_integration import CRMRequestError, crm_has, crm_request, lead_source

PARTNER_LEAD_SOURCE = "Connect Partner Lead"


def queue_partner_lead_sync(lead: str) -> None:
	"""Sends the lead's customer to Frappe's CRM in the background, so nobody waits on the CRM."""
	settings = frappe_crm()
	if not settings:
		return
	partner, customer = frappe.db.get_value("Partner Lead", lead, ["partner", "customer"])
	if customer and partner != settings.partner:
		_queue(customer)


def _queue(customer: str) -> None:
	frappe.db.set_value("Customer", customer, "frappe_crm_sync_status", "Queued", update_modified=False)
	frappe.enqueue(
		"connect.crm_partner_leads.sync_customer_lead",
		queue="short",
		# Without this, the worker can run before the change is saved, and miss it.
		enqueue_after_commit=True,
		customer=customer,
	)


def sync_customer_lead(customer: str) -> None:
	"""Background job: makes the customer's Lead if it has none, then writes each partner's note.
	One job per customer runs at a time, so two changes together can't make two Leads."""
	settings = frappe_crm()
	if not settings:
		return
	with filelock(f"connect_partner_lead_sync_{customer}", timeout=120):
		_sync_customer_lead(customer, settings)


def _sync_customer_lead(customer: str, settings) -> None:
	leads = _partner_leads(customer, settings.partner)
	if not leads:
		return

	doc = frappe.get_doc("Customer", customer)
	try:
		if not doc.frappe_crm_lead:
			response = crm_request(settings, "POST", "/api/resource/CRM Lead", json=lead_payload(doc, settings))
			doc.db_set("frappe_crm_lead", response.json()["data"]["name"], update_modified=False)
			frappe.db.commit()  # nosemgrep: the Lead is made: a failure below mustn't make another
		for lead in leads:
			_write_note(settings, doc.frappe_crm_lead, lead)
	except Exception:
		frappe.db.rollback()
		# Logged once, not every hour the retry meets the same broken CRM.
		if doc.frappe_crm_sync_status != "Failed":
			frappe.log_error(title=f"Frappe CRM sync failed for Customer {customer}")
		doc.db_set(
			{"frappe_crm_sync_status": "Failed", "frappe_crm_sync_error": frappe.get_traceback()[:2000]},
			update_modified=False,
		)
		return

	doc.db_set({"frappe_crm_sync_status": "Synced", "frappe_crm_sync_error": None}, update_modified=False)


def _partner_leads(customer: str, frappe_partner: str) -> list[dict]:
	"""The customer's leads with partners other than Frappe, each with its partner's name, owner and briefs."""
	Lead = frappe.qb.DocType("Partner Lead")
	Partner = frappe.qb.DocType("Partner")
	User = frappe.qb.DocType("User")
	leads = (
		frappe.qb.from_(Lead)
		.join(Partner)
		.on(Partner.name == Lead.partner)
		.left_join(User)
		.on(User.name == Lead.assigned_to)
		.select(
			Lead.name, Lead.stage, Lead.probability, Lead.lost_reason, Lead.frappe_crm_note,
			Partner.partner_name, User.full_name.as_("owner_name"),
		)
		.where((Lead.customer == customer) & (Lead.partner != frappe_partner))
		.orderby(Lead.creation)
		.run(as_dict=True)
	)
	briefs = _briefs([lead.name for lead in leads])
	for lead in leads:
		lead.briefs = briefs.get(lead.name, [])
	return leads


def _briefs(leads: list[str]) -> dict[str, list[dict]]:
	"""Each lead's briefs (Project Quotes) with their project's name, oldest first."""
	if not leads:
		return {}
	Quote = frappe.qb.DocType("Project Quote")
	Project = frappe.qb.DocType("Customer Project")
	rows = (
		frappe.qb.from_(Quote)
		.join(Project)
		.on(Project.name == Quote.customer_project)
		.select(Quote.lead, Project.project_name, Quote.status, Quote.amount, Quote.timeline_weeks)
		.where(Quote.lead.isin(leads))
		.orderby(Quote.creation)
		.run(as_dict=True)
	)
	by_lead = {}
	for row in rows:
		by_lead.setdefault(row.lead, []).append(row)
	return by_lead


def lead_payload(doc, settings) -> dict:
	"""The Lead's fields: the customer and the person on their side. Industry is a fixed list on the
	CRM, which refuses a Lead with a value it doesn't have, so one it lacks is left off."""
	person = _customer_contact(doc.name)
	payload = {
		"first_name": person.first_name or doc.customer_name,
		"last_name": person.last_name,
		"email": person.email,
		"mobile_no": person.mobile_no or person.phone,
		"organization": doc.customer_name,
		"website": doc.website,
		"industry": doc.industry if doc.industry and crm_has(settings, "CRM Industry", doc.industry) else None,
		"source": lead_source(settings, PARTNER_LEAD_SOURCE),
		"status": settings.default_lead_status,
	}
	return {key: value for key, value in payload.items() if value}


def _customer_contact(customer: str):
	"""The customer's admin, else anyone still on their team."""
	user = frappe.db.get_value(
		"Customer Team Member",
		{"customer": customer, "is_removed": 0},
		"user",
		order_by="is_admin desc, creation asc",
	)
	person = user and frappe.db.get_value(
		"User", user, ["first_name", "last_name", "email", "mobile_no", "phone"], as_dict=True
	)
	return person or frappe._dict()


def note_content(lead) -> str:
	"""Where the partner stands with the customer: the lead's stage and owner, then each brief."""
	facts = [
		("Stage", lead.stage),
		("Owner", lead.owner_name or _("Not assigned")),
		("Probability", lead.probability),
		("Lost because", lead.lost_reason),
	]
	content = "<p>" + " · ".join(f"<b>{_(label)}:</b> {escape_html(value)}" for label, value in facts if value) + "</p>"
	if lead.briefs:
		items = "".join(f"<li>{escape_html(_brief_line(brief))}</li>" for brief in lead.briefs)
		content += f"<p><b>{_('Requirements')}</b></p><ul>{items}</ul>"
	return content


def _brief_line(brief) -> str:
	parts = [brief.status]
	if brief.amount:
		parts.append(fmt_money(brief.amount, currency="INR"))
	if brief.timeline_weeks:
		parts.append(_("{0} weeks").format(brief.timeline_weeks))
	return f"{brief.project_name}: " + " · ".join(parts)


def _write_note(settings, crm_lead: str, lead) -> None:
	"""Updates the partner's note on the Lead, or writes it when there's none (or it was deleted there)."""
	note = {"title": lead.partner_name, "content": note_content(lead)}
	if lead.frappe_crm_note:
		try:
			crm_request(settings, "PUT", f"/api/resource/FCRM Note/{quote(lead.frappe_crm_note)}", json=note)
			return
		except CRMRequestError as e:
			if e.status_code != 404:
				raise

	response = crm_request(
		settings,
		"POST",
		"/api/resource/FCRM Note",
		json={**note, "reference_doctype": "CRM Lead", "reference_docname": crm_lead},
	)
	frappe.db.set_value("Partner Lead", lead.name, "frappe_crm_note", response.json()["data"]["name"], update_modified=False)
	frappe.db.commit()  # nosemgrep: the note is made: a failure on the next partner mustn't make another


def retry_partner_lead_sync() -> None:
	"""Hourly: sends the customers a failed or missed sync left behind."""
	if not frappe_crm():
		return
	for customer in frappe.get_all(
		"Customer", filters={"frappe_crm_sync_status": ["in", ["Queued", "Failed"]]}, pluck="name"
	):
		sync_customer_lead(customer)
		frappe.db.commit()  # nosemgrep: keep each customer's sync status, so a later failure doesn't send it again


@frappe.whitelist(methods=["POST"])
def send_to_frappe_crm(customer: str) -> None:
	"""Desk: sends one customer's partner leads to Frappe's CRM now, such as one from before sync began."""
	frappe.only_for("System Manager")
	settings = frappe_crm()
	if not settings:
		frappe.throw(_("Frappe's CRM isn't connected. Set it up in Partner CRM Settings first."))
	if not _partner_leads(customer, settings.partner):
		frappe.throw(_("This customer has no leads with partners yet."))
	_queue(customer)
