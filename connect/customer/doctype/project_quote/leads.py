# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import Order

from connect.customer.doctype.customer_project.brief import requirement_card
from connect.messaging.customer_identity import anonymous_company
from connect.partner.doctype.partner_customer.customer_records import (
	activity_of,
	add_note,
	follow_ups_of,
	log_follow_up,
	notes_of,
)
from connect.notifications import _message_preview_text
from connect.permissions import _is_partner_admin, _my_active_partner

CLOSED_STAGES = ("Won", "Lost", "Junk", "Closed")
LEAD_LIMIT = 500


def my_leads() -> dict:
	"""The partner's Leads page: each brief the partner got, newest reply first. An owner sees
	every lead; anyone else, the leads whose thread they are on."""
	partner = _my_active_partner(frappe.session.user)
	team = partner_team(partner)
	team_users = {member.user for member in team}
	rows = _lead_query(partner).limit(LEAD_LIMIT).run(as_dict=True)
	return {
		"me": frappe.session.user,
		"team": team,
		"leads": [_list_row(row, team_users) for row in rows],
	}


def get_lead(name: str) -> dict:
	"""One lead: its brief, the customer, and every message in the customer's thread."""
	row = _get_lead_row(name)
	team = partner_team(row.partner)
	team_users = {member.user for member in team}
	card = _brief_card(row)
	return {
		"me": frappe.session.user,
		"team": team,
		"lead": {
			**_list_row(row, team_users),
			**_brief_fields(card),
			"thread": row.thread,
			"thread_closed": row.thread_status == "Closed",
			"partner_name": row.partner_name,
			# Until the customer is interested in the partner's quote, they stay anonymous.
			"contact": _contact(row.customer_user) if row.is_customer_revealed else {},
			"messages": _lead_messages(row, team_users),
			**_lead_records(row),
		},
	}


def add_lead_note(name: str, content: str) -> list[dict]:
	"""Adds the team's note on the lead's customer and returns the customer's notes."""
	row = _get_lead_row(name)
	add_note(row.partner, row.customer, content, quote=row.name)
	return notes_of(row.partner, row.customer)


def log_lead_follow_up(name: str, values: dict) -> dict:
	row = _get_lead_row(name)
	log_follow_up(row.partner, row.customer, frappe.parse_json(values), quote=row.name)
	return _lead_records(row)


def update_lead(name: str, stage=None, owner=None, probability=None, lost_reason=None) -> dict:
	"""Sets what the partner's sales team changed on the lead. A None value is left as it is;
	an empty owner unassigns the lead."""
	row = _get_lead_row(name)
	doc = frappe.get_doc("Project Quote", row.name)
	if stage is not None:
		_check_stage_change(doc, stage)
		doc.lead_stage = stage
		doc.lost_reason = lost_reason
	if owner is not None:
		doc.lead_owner = owner or None
	if probability is not None:
		doc.probability = probability
	# Project Quote is a system DocType; _get_lead_row has checked this user may work the lead.
	# Activity is read from the Version history, so it's recorded even where Frappe would skip it.
	doc.save(ignore_permissions=True, ignore_version=False)
	return {
		"stage": doc.lead_stage,
		"owner": doc.lead_owner,
		"probability": doc.probability,
		"lost_reason": doc.lost_reason,
	}


def partner_team(partner: str) -> list[dict]:
	"""The partner's active members, who a lead can be assigned to."""
	Member = frappe.qb.DocType("Connect Partner Member")
	User = frappe.qb.DocType("User")
	return (
		frappe.qb.from_(Member)
		.join(User)
		.on(User.name == Member.user)
		.select(Member.user, User.full_name)
		.where(Member.partner == partner)
		.where(Member.is_removed == 0)
		.orderby(User.full_name)
		.run(as_dict=True)
	)


def _lead_query(partner: str):
	Quote = frappe.qb.DocType("Project Quote")
	Project = frappe.qb.DocType("Customer Project")
	Thread = frappe.qb.DocType("Connect Thread")
	Customer = frappe.qb.DocType("Customer")
	Owner = frappe.qb.DocType("User")
	query = (
		frappe.qb.from_(Quote)
		.join(Project)
		.on(Project.name == Quote.customer_project)
		.join(Thread)
		.on(Thread.name == Quote.thread)
		.left_join(Customer)
		.on(Customer.name == Thread.customer)
		.left_join(Owner)
		.on(Owner.name == Quote.lead_owner)
		.select(
			Quote.name, Quote.partner, Quote.thread, Quote.status, Quote.lead_stage, Quote.lead_owner,
			Quote.probability, Quote.lost_reason, Quote.brief_message, Quote.quote_message, Quote.creation,
			Project.name.as_("project"), Project.project_name, Project.user.as_("customer_user"),
			Customer.name.as_("customer"), Customer.customer_name,
			Thread.status.as_("thread_status"), Thread.last_message_at, Thread.last_message_sender,
			Thread.is_customer_revealed,
			Owner.full_name.as_("owner_name"),
		)
		.where(Quote.partner == partner)
		.orderby(Thread.last_message_at, order=Order.desc)
	)
	if _is_partner_admin(partner, frappe.session.user):
		return query
	return query.where(Quote.thread.isin(_my_thread_ids()))


def _my_thread_ids():
	Member = frappe.qb.DocType("Connect Thread Member")
	return (
		frappe.qb.from_(Member)
		.select(Member.thread)
		.where(Member.user == frappe.session.user)
		.where(Member.is_removed == 0)
	)


def _get_lead_row(name: str):
	"""The lead, if this user may work it: the same scope as their Leads list."""
	Quote = frappe.qb.DocType("Project Quote")
	Partner = frappe.qb.DocType("Partner")
	rows = (
		_lead_query(_my_active_partner(frappe.session.user))
		.left_join(Partner)
		.on(Partner.name == Quote.partner)
		.select(Partner.partner_name)
		.where(Quote.name == name)
		.run(as_dict=True)
	)
	if not rows:
		frappe.throw(_("Lead not found."), frappe.DoesNotExistError)
	return rows[0]


def _lead_records(row) -> dict:
	"""The team's own records on the lead. Notes and follow-ups are about the customer, so they
	show on all of the customer's leads; Activity is this lead's own."""
	follow_ups = follow_ups_of(row.partner, row.customer)
	company = (row.customer_name or row.customer) if row.is_customer_revealed else anonymous_company()
	brief = {"name": row.name, "at": row.creation, "by": company}
	own_follow_ups = [follow_up for follow_up in follow_ups if follow_up["quote"] == row.name]
	return {
		"notes": notes_of(row.partner, row.customer),
		"follow_ups": follow_ups,
		"activity": activity_of({"Project Quote": [row.name]}, [brief], own_follow_ups),
	}


def _check_stage_change(doc, stage: str):
	if doc.status == "Hired":
		frappe.throw(_("The customer hired you, so this lead stays Won."))
	if stage == "Won":
		frappe.throw(_("A lead is won when the customer hires you."))


def _list_row(row, team_users: set[str]) -> dict:
	is_closed = row.lead_stage in CLOSED_STAGES
	waiting = bool(row.last_message_sender) and row.last_message_sender not in team_users
	return {
		"name": row.name,
		"project": row.project,
		"project_name": row.project_name,
		"company": (row.customer_name or row.customer) if row.is_customer_revealed else anonymous_company(),
		"is_customer_revealed": bool(row.is_customer_revealed),
		"stage": row.lead_stage,
		"owner": row.lead_owner,
		"owner_name": row.owner_name,
		"probability": row.probability,
		"lost_reason": row.lost_reason,
		"is_hired": row.status == "Hired",
		"needs_reply": waiting and not is_closed,
		"last_message_at": row.last_message_at or row.creation,
	}


def _brief_card(row) -> dict:
	"""The Requirement card the partner received, or the project's card as it is today for a
	brief sent before Connect kept the message."""
	if row.brief_message:
		content = frappe.db.get_value("Connect Message", row.brief_message, "content")
		if content:
			return frappe.parse_json(content)
	project = frappe.get_doc("Customer Project", row.project)
	return requirement_card(project, row.customer)


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
		"scope": card.get("description") or card.get("looking_for") or "",
		"budget": card.get("budget"),
		"industry": card.get("industry"),
		"project_rows": [[label, value] for label, value in rows if value],
		"asked_for": [card["partner_brief"]] if card.get("partner_brief") else [],
	}


def _contact(user: str) -> dict:
	contact = frappe.db.get_value("User", user, ["full_name", "email", "mobile_no"], as_dict=True) or {}
	return {"name": contact.get("full_name"), "email": contact.get("email"), "phone": contact.get("mobile_no")}


def _lead_messages(row, team_users: set[str]) -> list[dict]:
	# The thread is the customer's whole conversation with the partner, so the lead starts at
	# its own brief; later briefs show as one line each. Read without permission checks:
	# _get_lead_row has scoped the thread.
	filters = {"thread": row.thread}
	if row.brief_message:
		filters["creation"] = [">=", frappe.db.get_value("Connect Message", row.brief_message, "creation")]
	messages = frappe.get_all(
		"Connect Message",
		filters=filters,
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
			**_message_body(message, row),
		}
		for message in messages
	]


def _message_body(message, row) -> dict:
	"""What a message shows on the lead: this lead's brief and quote as cards, the rest as text."""
	if message.name == row.brief_message:
		return {"kind": "brief"}
	if message.message_type == "Quote" and message.name == row.quote_message:
		quote = frappe.parse_json(message.content or "{}") or {}
		return {"kind": "bid", "amount": quote.get("amount"), "weeks": quote.get("weeks"), "note": quote.get("note")}
	if message.message_type == "Requirement":
		card = frappe.parse_json(message.content or "{}") or {}
		return {"kind": "text", "text": _("Shared the brief “{0}”").format(card.get("project_name") or _("a project"))}
	if message.message_type in ("Quote", "Hire Request") and _is_other_project(message, row):
		return {"kind": "text", "text": _("{0}, for another brief").format(_message_preview_text(message))}
	if message.message_type == "File":
		return {"kind": "text", "text": message.content or message.file_name, "file_url": message.attachment}
	if message.message_type == "Text":
		return {"kind": "text", "text": message.content}
	return {"kind": "text", "text": _message_preview_text(message)}


def _author(sender: str, names: dict, team_users: set[str], is_customer_revealed: bool) -> str:
	if sender not in team_users and not is_customer_revealed:
		return anonymous_company()
	return names.get(sender) or sender


def _is_other_project(message, row) -> bool:
	project = (frappe.parse_json(message.content or "{}") or {}).get("project")
	return bool(project) and project != row.project


def _user_names(users: set[str]) -> dict:
	if not users:
		return {}
	return dict(frappe.get_all("User", filters={"name": ["in", list(users)]}, fields=["name", "full_name"], as_list=True))
