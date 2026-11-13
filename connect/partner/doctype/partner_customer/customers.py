# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import Order

from connect.customer.doctype.project_quote.leads import lead_messages, partner_side_users, partner_team
from connect.partner.central_billing import customer_billing
from connect.partner.doctype.partner_customer.customer_records import (
	activity_of,
	add_note,
	follow_ups_of,
	log_follow_up,
	notes_of,
)
from connect.partner.doctype.connect_partner_member.connect_partner_member import CUSTOMER_ACCESS
from connect.permissions import _check_can_write, _my_partner_with_access


def my_customers() -> dict:
	"""The partner's Customers page: Owners, Sales and Finance see all of the team's customers."""
	partner = _my_partner_with_access(frappe.session.user, CUSTOMER_ACCESS)
	rows = _customer_query(partner).run(as_dict=True)
	billing = customer_billing(rows)
	return {
		"me": frappe.session.user,
		"team": partner_team(partner, CUSTOMER_ACCESS),
		"customers": [_customer_dict(row, billing[row.name]) for row in rows],
	}


def get_customer(name: str) -> dict:
	"""One customer with the team's notes, follow-ups and the whole history with them."""
	row = _get_customer_row(name)
	threads = _customer_threads(row)
	quotes = frappe.get_all(
		"Project Quote",
		filters={"partner": row.partner, "thread": ["in", threads]},
		fields=["name", "creation", "status", "brief_message", "customer_project.project_name"],
	)
	follow_ups = follow_ups_of(row.partner, row.customer)
	briefs = [
		{"name": quote.name, "at": quote.creation, "by": row.customer_name, "project_name": quote.project_name}
		for quote in quotes
	]
	leads = frappe.get_all("Partner Lead", filters={"partner": row.partner, "thread": ["in", threads]}, pluck="name")
	records = {
		"Partner Lead": leads,
		"Project Quote": [quote.name for quote in quotes],
		"Partner Customer": [row.name],
	}
	return {
		"me": frappe.session.user,
		"team": partner_team(row.partner, CUSTOMER_ACCESS),
		"customer": {
			**_customer_dict(row, customer_billing([row])[row.name]),
			"notes": notes_of(row.partner, row.customer),
			"follow_ups": follow_ups,
			"activity": activity_of(records, briefs, follow_ups),
			**_conversation(row, threads, quotes),
		},
	}


def _conversation(row, threads: list[str], quotes: list) -> dict:
	"""The customer's chat with the partner, as their lead showed it. A customer the partner
	added on their own has none."""
	if not threads:
		return {"thread": None, "thread_closed": True, "is_customer_revealed": True, "messages": []}
	thread = threads[0]
	return {
		"thread": thread,
		"thread_closed": frappe.db.get_value("Connect Thread", thread, "status") == "Closed",
		# A customer has hired the partner, so the partner knows who they are.
		"is_customer_revealed": True,
		"messages": lead_messages(thread, partner_side_users(row.partner), quotes, is_customer_revealed=True),
	}


def update_customer(name: str, stage=None, assigned_to=None) -> dict:
	"""Sets what the team changed. A None value is left as it is; an empty owner unassigns.
	Moving a customer who wants to link to Onboarding approves the link."""
	row = _get_customer_row(name)
	doc = frappe.get_doc("Partner Customer", row.name)
	if stage is not None:
		doc.stage = stage
	if assigned_to is not None:
		doc.assigned_to = assigned_to or None
	# Partner Customer is a system DocType; _get_customer_row checked this user works with it.
	# Activity is read from the Version history, so it's recorded even where Frappe would skip it.
	doc.save(ignore_permissions=True, ignore_version=False)
	return {"stage": doc.stage, "assigned_to": doc.assigned_to}


def add_customer_note(name: str, content: str) -> list[dict]:
	row = _get_customer_row(name)
	add_note(row.partner, row.customer, content)
	return notes_of(row.partner, row.customer)


def log_customer_follow_up(name: str, values: dict) -> dict:
	"""Logs a follow-up on the customer, or with a meeting link, invites them to a meeting in
	their thread."""
	row = _get_customer_row(name)
	values = frappe.parse_json(values)
	thread = None
	if values.get("meeting_link"):
		thread = _thread_to_invite_in(row)
	log_follow_up(row.partner, row.customer, values, thread=thread)
	return get_customer(name)["customer"]


def _thread_to_invite_in(row) -> str:
	"""The customer's thread, with the caller in it: the invite is posted there as this person."""
	from connect.messaging.doctype.connect_thread.connect_thread import ensure_partner_member

	threads = _customer_threads(row)
	if not threads:
		frappe.throw(_("This customer has no chat on Connect to send an invite in."))
	ensure_partner_member(threads[0], frappe.session.user, frappe.session.user)
	_check_can_write(threads[0], frappe.session.user)
	return threads[0]


def _customer_query(partner: str):
	Record = frappe.qb.DocType("Partner Customer")
	Customer = frappe.qb.DocType("Customer")
	Project = frappe.qb.DocType("Customer Project")
	Contact = frappe.qb.DocType("User").as_("contact_user")
	Owner = frappe.qb.DocType("User").as_("owner_user")
	return (
		frappe.qb.from_(Record)
		.left_join(Customer)
		.on(Customer.name == Record.customer)
		.left_join(Project)
		.on(Project.name == Record.project)
		.left_join(Contact)
		.on(Contact.name == Project.user)
		.left_join(Owner)
		.on(Owner.name == Record.assigned_to)
		.select(
			Record.name, Record.partner, Record.customer, Record.stage, Record.assigned_to, Record.source,
			Record.converted_on, Record.creation, Record.billing_by, Record.linked_on,
			Customer.customer_name, Customer.industry, Customer.country,
			Project.project_name,
			Contact.full_name.as_("contact"), Contact.email, Contact.mobile_no.as_("phone"),
			Owner.full_name.as_("assigned_to_name"),
		)
		.where(Record.partner == partner)
		.orderby(Record.creation, order=Order.desc)
	)


def _get_customer_row(name: str):
	"""The customer, if this user may work with them: the same scope as their Customers list."""
	Record = frappe.qb.DocType("Partner Customer")
	rows = _customer_query(_my_partner_with_access(frappe.session.user, CUSTOMER_ACCESS)).where(Record.name == name).run(as_dict=True)
	if not rows:
		frappe.throw(_("Customer not found."), frappe.DoesNotExistError)
	return rows[0]


def _customer_threads(row) -> list[str]:
	"""The customer's threads with the partner, the one written in last first."""
	return frappe.get_all(
		"Connect Thread",
		filters={"partner": row.partner, "customer": row.customer},
		pluck="name",
		order_by="last_message_at desc",
	)


def _customer_dict(row, billing: dict) -> dict:
	"""The customer as both pages read it. Sites and MRR come from Frappe Cloud (demo for now)."""
	return {
		"name": row.name,
		"company": row.customer_name or row.customer,
		"stage": row.stage,
		"assigned_to": row.assigned_to,
		"assigned_to_name": row.assigned_to_name,
		"source": row.source,
		"project_name": row.project_name,
		"converted_on": row.converted_on,
		"contact": row.contact,
		"email": row.email,
		"phone": row.phone,
		"industry": row.industry,
		"country": row.country,
		"billing_by": row.billing_by,
		"linked_on": row.linked_on,
		**billing,
	}
