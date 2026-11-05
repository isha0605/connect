# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import Order

from connect.crm_integration import crm_settings
from connect.customer.doctype.customer_project.brief import requirement_card
from connect.messaging.customer_identity import anonymous_company
from connect.notifications import _message_preview_text
from connect.partner.doctype.connect_partner_member.connect_partner_member import (
	ACCESS_LEVELS,
	LEAD_ACCESS,
	access_level_of,
)
from connect.partner.doctype.partner_customer.customer_records import (
	activity_of,
	add_note,
	follow_ups_of,
	log_follow_up,
	notes_of,
)
from connect.partner.doctype.partner_lead.partner_lead import CLOSED_STAGES
from connect.permissions import _check_can_write, _is_partner_admin, _my_partner_with_access

LEAD_LIMIT = 500

# A requirement's quote status, as the partner reads it on their lead.
REQUIREMENT_STATUSES = {
	"Awaiting": "Waiting for your quote",
	"Quoted": "Quoted",
	"Interested": "Interested",
	"Not Interested": "Not interested",
	"Hire Requested": "Wants to hire you",
	"Hired": "Hired you",
	"Hire Declined": "Hire declined",
}


def my_leads() -> dict:
	"""The partner's Leads page: one lead per customer conversation, newest reply first. Owners
	and Sales see all of the team's leads."""
	partner = _my_partner_with_access(frappe.session.user, LEAD_ACCESS)
	partner_side = _partner_side(partner)
	rows = _lead_query(partner).limit(LEAD_LIMIT).run(as_dict=True)
	requirements = _requirements_by_lead([row.name for row in rows])
	return {
		"me": frappe.session.user,
		"team": lead_team(partner),
		"leads": [_list_row(row, requirements[row.name], partner_side) for row in rows if row.name in requirements],
	}


def get_lead(name: str) -> dict:
	"""One lead: every requirement the customer sent, the newest one's brief, and their whole
	conversation with the partner."""
	row = _get_lead_row(name)
	team = lead_team(row.partner)
	team_users = {member.user for member in team}
	requirements = _requirements_by_lead([row.name]).get(row.name)
	if not requirements:
		frappe.throw(_("Lead not found."), frappe.DoesNotExistError)

	latest = requirements[0]
	return {
		"me": frappe.session.user,
		"team": team,
		"can_invite": _is_partner_admin(row.partner, frappe.session.user),
		"lead": {
			**_list_row(row, requirements, _partner_side(row.partner)),
			**_brief_fields(_brief_card(latest, row.customer)),
			"thread": row.thread,
			"thread_closed": row.thread_status == "Closed",
			"partner_name": row.partner_name,
			# Until the customer is interested in the partner's quote, they stay anonymous.
			"contact": _contact(latest.customer_user) if row.is_customer_revealed else {},
			"requirements": [_requirement_row(requirement) for requirement in requirements],
			**_crm_owner(row),
			"messages": _lead_messages(row, team_users),
			**_lead_records(row, requirements),
		},
	}


def add_lead_note(name: str, content: str) -> list[dict]:
	"""Adds the team's note on the lead's customer and returns the customer's notes."""
	row = _get_lead_row(name)
	add_note(row.partner, row.customer, content)
	return notes_of(row.partner, row.customer)


def log_lead_follow_up(name: str, values: dict) -> dict:
	"""Logs a follow-up on the lead's customer, or with a meeting link, invites them to a meeting
	in their thread."""
	row = _get_lead_row(name)
	values = frappe.parse_json(values)
	if values.get("meeting_link"):
		_check_can_write(row.thread, frappe.session.user)
	log_follow_up(row.partner, row.customer, values, thread=row.thread)
	return _lead_records(row, _requirements_by_lead([row.name]).get(row.name, []))


def update_lead(name: str, stage=None, owner=None, probability=None, lost_reason=None) -> dict:
	"""Sets what the partner's sales team changed on the lead. A None value is left as it is;
	an empty owner unassigns the lead."""
	row = _get_lead_row(name)
	doc = frappe.get_doc("Partner Lead", row.name)
	if stage is not None:
		_check_stage_change(doc, stage)
		doc.stage = stage
		doc.lost_reason = lost_reason
	if owner is not None:
		doc.assigned_to = owner or None
	if probability is not None:
		doc.probability = probability
	# Partner Lead is a system DocType; _get_lead_row has checked this user may work the lead.
	# Activity is read from the Version history, so it's recorded even where Frappe would skip it.
	doc.save(ignore_permissions=True, ignore_version=False)
	return {
		"stage": doc.stage,
		"owner": doc.assigned_to,
		"probability": doc.probability,
		"lost_reason": doc.lost_reason,
	}


def partner_team(partner: str, levels=ACCESS_LEVELS) -> list[dict]:
	"""The partner's active members with one of these access levels: who a lead (Owner or
	Sales) or a customer can be assigned to."""
	Member = frappe.qb.DocType("Connect Partner Member")
	User = frappe.qb.DocType("User")
	rows = (
		frappe.qb.from_(Member)
		.join(User)
		.on(User.name == Member.user)
		.select(Member.user, User.full_name, Member.is_admin, Member.access, Member.crm_user)
		.where(Member.partner == partner)
		.where(Member.is_removed == 0)
		.orderby(User.full_name)
		.run(as_dict=True)
	)
	return [
		frappe._dict(user=row.user, full_name=row.full_name, crm_user=row.crm_user)
		for row in rows
		if access_level_of(row) in levels
	]


def lead_team(partner: str) -> list[dict]:
	"""Who a lead can be assigned to. With CRM sync on, each says whether they are on the CRM:
	someone who isn't can't take a lead until they are."""
	has_crm = bool(crm_settings(partner))
	return [
		frappe._dict(user=member.user, full_name=member.full_name, in_crm=bool(member.crm_user) if has_crm else None)
		for member in partner_team(partner, LEAD_ACCESS)
	]


def _lead_query(partner: str):
	Lead = frappe.qb.DocType("Partner Lead")
	Thread = frappe.qb.DocType("Connect Thread")
	Customer = frappe.qb.DocType("Customer")
	Owner = frappe.qb.DocType("User")
	return (
		frappe.qb.from_(Lead)
		.join(Thread)
		.on(Thread.name == Lead.thread)
		.left_join(Customer)
		.on(Customer.name == Lead.customer)
		.left_join(Owner)
		.on(Owner.name == Lead.assigned_to)
		.select(
			Lead.name, Lead.partner, Lead.thread, Lead.customer, Lead.stage, Lead.assigned_to,
			Lead.probability, Lead.lost_reason, Lead.crm_owner, Lead.creation,
			Customer.customer_name,
			Thread.status.as_("thread_status"), Thread.last_message_at, Thread.last_message_sender,
			Thread.is_customer_revealed,
			Owner.full_name.as_("owner_name"),
		)
		.where(Lead.partner == partner)
		.orderby(Thread.last_message_at, order=Order.desc)
	)


def _get_lead_row(name: str):
	"""The lead, if this user may work it: the same scope as their Leads list."""
	Lead = frappe.qb.DocType("Partner Lead")
	Partner = frappe.qb.DocType("Partner")
	rows = (
		_lead_query(_my_partner_with_access(frappe.session.user, LEAD_ACCESS))
		.left_join(Partner)
		.on(Partner.name == Lead.partner)
		.select(Partner.partner_name)
		.where(Lead.name == name)
		.run(as_dict=True)
	)
	if not rows:
		frappe.throw(_("Lead not found."), frappe.DoesNotExistError)
	return rows[0]


def _requirements_by_lead(leads: list[str]) -> dict[str, list]:
	"""Each lead's requirements, newest first. Read without permission checks: callers have
	scoped the leads to the user's partner."""
	if not leads:
		return {}
	rows = frappe.get_all(
		"Project Quote",
		filters={"lead": ["in", leads]},
		fields=[
			"name", "lead", "status", "creation", "brief_message",
			"customer_project as project",
			"customer_project.project_name as project_name",
			"customer_project.user as customer_user",
		],
		order_by="creation desc",
	)
	by_lead = {}
	for row in rows:
		by_lead.setdefault(row.lead, []).append(row)
	return by_lead


def _lead_records(row, requirements: list) -> dict:
	"""The team's own records on the lead's customer: notes, follow-ups, and the Activity of
	the lead and each requirement in it."""
	follow_ups = follow_ups_of(row.partner, row.customer)
	briefs = [
		{"name": requirement.name, "at": requirement.creation, "by": _company(row), "project_name": requirement.project_name}
		for requirement in requirements
	]
	records = {"Partner Lead": [row.name], "Project Quote": [requirement.name for requirement in requirements]}
	return {
		"notes": notes_of(row.partner, row.customer),
		"follow_ups": follow_ups,
		"activity": activity_of(records, briefs, follow_ups),
	}


def _check_stage_change(doc, stage: str):
	if doc.stage == "Won":
		frappe.throw(_("The customer hired you, so this lead stays Won."))
	if stage == "Won":
		frappe.throw(_("A lead is won when the customer hires you."))


def _partner_side(partner: str) -> set[str]:
	"""Everyone who writes for the partner, people since removed included: a message from any of
	them is the partner's reply."""
	return set(frappe.get_all("Connect Partner Member", filters={"partner": partner}, pluck="user"))


def _list_row(row, requirements: list, partner_side: set[str]) -> dict:
	latest = requirements[0]
	is_closed = row.stage in CLOSED_STAGES
	# As Frappe CRM's communication status: Open while the customer wrote last, Replied once the
	# partner has answered.
	waiting = bool(row.last_message_sender) and row.last_message_sender not in partner_side
	return {
		"name": row.name,
		"project": latest.project,
		"project_name": latest.project_name,
		"requirement_count": len(requirements),
		"requirement_names": [requirement.project_name for requirement in requirements],
		"company": _company(row),
		"is_customer_revealed": bool(row.is_customer_revealed),
		"stage": row.stage,
		"owner": row.assigned_to,
		"owner_name": row.owner_name,
		"probability": row.probability,
		"lost_reason": row.lost_reason,
		"is_hired": any(requirement.status == "Hired" for requirement in requirements),
		"communication_status": "Open" if waiting else "Replied",
		"needs_reply": waiting and not is_closed,
		"last_message_at": row.last_message_at or row.creation,
	}


def _requirement_row(requirement) -> dict:
	return {
		"name": requirement.name,
		"project_name": requirement.project_name,
		"status": requirement.status,
		"status_label": _(REQUIREMENT_STATUSES.get(requirement.status, requirement.status)),
		"at": requirement.creation,
	}


def _crm_owner(row) -> dict:
	"""Who has the lead on the CRM when that person can't take it on Connect, and whether
	they are on the team at all (an owner can invite them when they aren't)."""
	if not row.crm_owner:
		return {"crm_owner": None, "crm_owner_on_team": False}
	on_team = frappe.db.exists(
		"Connect Partner Member", {"partner": row.partner, "user": row.crm_owner, "is_removed": 0}
	)
	return {"crm_owner": row.crm_owner, "crm_owner_on_team": bool(on_team)}


def _company(row) -> str:
	return (row.customer_name or row.customer) if row.is_customer_revealed else anonymous_company()


def _brief_card(requirement, customer: str) -> dict:
	"""The Requirement card the partner received, or the project's card as it is today for a
	brief sent before Connect kept the message."""
	if requirement.brief_message:
		content = frappe.db.get_value("Connect Message", requirement.brief_message, "content")
		if content:
			return frappe.parse_json(content)
	return requirement_card(frappe.get_doc("Customer Project", requirement.project), customer)


def _brief_fields(card: dict) -> dict:
	rows = [
		(_("Budget"), card.get("budget")),
		(_("Industry"), card.get("industry")),
		(_("Country"), card.get("country")),
		(_("Size"), card.get("company_size")),
		(_("Current operations"), card.get("current_situation")),
		(_("Go live"), card.get("timeline")),
		(_("Delivery"), card.get("delivery_preference")),
	]
	return {
		"scope": _scope(card),
		"budget": card.get("budget"),
		"industry": card.get("industry"),
		"project_rows": [[label, value] for label, value in rows if value],
		"asked_for": [card["partner_brief"]] if card.get("partner_brief") else [],
	}


def _scope(card: dict) -> str:
	return card.get("description") or card.get("looking_for") or ""


def _contact(user: str) -> dict:
	contact = frappe.db.get_value("User", user, ["full_name", "email", "mobile_no"], as_dict=True) or {}
	return {"name": contact.get("full_name"), "email": contact.get("email"), "phone": contact.get("mobile_no")}


def _lead_messages(row, team_users: set[str]) -> list[dict]:
	"""The customer's whole conversation with the partner: the lead is all of it. Read without
	permission checks: _get_lead_row has scoped the thread."""
	messages = frappe.get_all(
		"Connect Message",
		filters={"thread": row.thread},
		fields=["name", "sender", "message_type", "content", "file_name", "attachment", "reply_to", "creation"],
		order_by="creation asc",
	)
	names = _user_names({message.sender for message in messages})
	return [
		{
			"id": message.name,
			"from": "you" if message.sender in team_users else "them",
			"author": _author(message.sender, names, team_users, row.is_customer_revealed),
			"at": message.creation,
			"reply_to": message.reply_to,
			**_message_body(message),
		}
		for message in messages
	]


def _message_body(message) -> dict:
	"""What a message shows on the lead: each brief and quote as a card, the rest as text."""
	if message.message_type == "Requirement":
		card = frappe.parse_json(message.content or "{}") or {}
		return {
			"kind": "brief",
			"title": card.get("project_name") or _("A project"),
			"scope": _scope(card),
			"budget": card.get("budget"),
			"industry": card.get("industry"),
		}
	if message.message_type == "Quote":
		quote = frappe.parse_json(message.content or "{}") or {}
		return {
			"kind": "bid",
			"title": quote.get("project_name"),
			"amount": quote.get("amount"),
			"weeks": quote.get("weeks"),
			"note": quote.get("note"),
		}
	if message.message_type == "Meeting":
		meeting = frappe.parse_json(message.content or "{}") or {}
		return {
			"kind": "meeting",
			"title": meeting.get("title") or _("Kickoff call"),
			"starts_at": meeting.get("starts_at"),
			"link": meeting.get("link"),
			"duration_minutes": meeting.get("duration_minutes"),
			"agenda": meeting.get("agenda"),
			"follow_up": meeting.get("follow_up"),
		}
	if message.message_type == "File":
		return {"kind": "text", "text": message.content or message.file_name, "file_url": message.attachment}
	if message.message_type == "Text":
		return {"kind": "text", "text": message.content}
	return {"kind": "text", "text": _message_preview_text(message)}


def _author(sender: str, names: dict, team_users: set[str], is_customer_revealed: bool) -> str:
	if sender not in team_users and not is_customer_revealed:
		return anonymous_company()
	return names.get(sender) or sender


def _user_names(users: set[str]) -> dict:
	if not users:
		return {}
	return dict(frappe.get_all("User", filters={"name": ["in", list(users)]}, fields=["name", "full_name"], as_list=True))
