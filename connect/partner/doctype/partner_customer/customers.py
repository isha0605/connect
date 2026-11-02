# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import Order

from connect.customer.doctype.project_quote.leads import partner_team
from connect.partner.doctype.partner_customer.customer_records import (
	activity_of,
	add_note,
	follow_ups_of,
	log_follow_up,
	notes_of,
)
from connect.permissions import _is_partner_admin, _my_active_partner


def my_customers() -> dict:
	"""The partner's Customers page: an owner sees every customer; anyone else, the ones assigned
	to them or whose chat they are on."""
	partner = _my_active_partner(frappe.session.user)
	return {
		"me": frappe.session.user,
		"team": partner_team(partner),
		"customers": [_customer_dict(row) for row in _customer_query(partner).run(as_dict=True)],
	}


def get_customer(name: str) -> dict:
	"""One customer with the team's notes, follow-ups and the whole history with them."""
	row = _get_customer_row(name)
	quotes = frappe.get_all(
		"Project Quote",
		filters={"partner": row.partner, "thread": ["in", _customer_threads(row)]},
		fields=["name", "creation", "customer_project.project_name"],
	)
	follow_ups = follow_ups_of(row.partner, row.customer)
	briefs = [
		{"name": quote.name, "at": quote.creation, "by": row.customer_name, "project_name": quote.project_name}
		for quote in quotes
	]
	records = {"Project Quote": [quote.name for quote in quotes], "Partner Customer": [row.name]}
	return {
		"me": frappe.session.user,
		"team": partner_team(row.partner),
		"customer": {
			**_customer_dict(row),
			"notes": notes_of(row.partner, row.customer),
			"follow_ups": follow_ups,
			"activity": activity_of(records, briefs, follow_ups),
		},
	}


def update_customer(name: str, stage=None, assigned_to=None) -> dict:
	"""Sets what the team changed. A None value is left as it is; an empty owner unassigns."""
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
	row = _get_customer_row(name)
	log_follow_up(row.partner, row.customer, frappe.parse_json(values))
	return get_customer(name)["customer"]


def _customer_query(partner: str):
	Record = frappe.qb.DocType("Partner Customer")
	Customer = frappe.qb.DocType("Customer")
	Project = frappe.qb.DocType("Customer Project")
	Contact = frappe.qb.DocType("User").as_("contact_user")
	Owner = frappe.qb.DocType("User").as_("owner_user")
	query = (
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
			Record.converted_on, Record.creation,
			Customer.customer_name, Customer.industry, Customer.country,
			Project.project_name,
			Contact.full_name.as_("contact"), Contact.email, Contact.mobile_no.as_("phone"),
			Owner.full_name.as_("assigned_to_name"),
		)
		.where(Record.partner == partner)
		.orderby(Record.creation, order=Order.desc)
	)
	if _is_partner_admin(partner, frappe.session.user):
		return query
	return query.where((Record.assigned_to == frappe.session.user) | Record.customer.isin(_my_customers_by_chat(partner)))


def _my_customers_by_chat(partner: str):
	Thread = frappe.qb.DocType("Connect Thread")
	Member = frappe.qb.DocType("Connect Thread Member")
	return (
		frappe.qb.from_(Thread)
		.join(Member)
		.on(Member.thread == Thread.name)
		.select(Thread.customer)
		.where(Thread.partner == partner)
		.where(Member.user == frappe.session.user)
		.where(Member.is_removed == 0)
	)


def _get_customer_row(name: str):
	"""The customer, if this user may work with them: the same scope as their Customers list."""
	Record = frappe.qb.DocType("Partner Customer")
	rows = _customer_query(_my_active_partner(frappe.session.user)).where(Record.name == name).run(as_dict=True)
	if not rows:
		frappe.throw(_("Customer not found."), frappe.DoesNotExistError)
	return rows[0]


def _customer_threads(row) -> list[str]:
	return frappe.get_all("Connect Thread", filters={"partner": row.partner, "customer": row.customer}, pluck="name")


def _customer_dict(row) -> dict:
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
	}
