# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.partner.doctype.partner.partner import PARTNER_FIELDS, _apps_by_partner, attach_success_story_previews


class Shortlist(Document):
	pass


def _customer_names_for_user(user):
	return frappe.get_all("Customer Team Member", filters={"user": user}, pluck="customer")


def get_permission_query_conditions(user):
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return ""
	customers = _customer_names_for_user(user)
	if not customers:
		return "1=0"
	ShortlistTable = frappe.qb.DocType("Shortlist")
	return ShortlistTable.customer.isin(customers).get_sql()


def has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return True
	return doc.customer in _customer_names_for_user(user)


def get_my_shortlisted_partner_names():
	"""Returns the current user's shortlisted partner names, to mark bookmark state without refetching full partner data."""
	customer = get_customer_for_user()
	if not customer:
		return []
	return frappe.get_all("Shortlist", filters={"customer": customer}, pluck="partner")


def add_to_shortlist(partner):
	"""Idempotent: a second call for an already-shortlisted partner is a silent no-op rather than
	an error, matching the UI's bookmark-toggle semantics. Relies on the (customer, partner)
	unique constraint on Shortlist (see connect.patches.add_shortlist_unique_constraint) to
	reject a duplicate instead of checking for one first."""
	customer = get_customer_for_user()
	if not customer:
		frappe.throw("Your account isn't linked to a customer company yet.", frappe.PermissionError)
	try:
		frappe.get_doc({"doctype": "Shortlist", "customer": customer, "partner": partner}).insert(
			ignore_permissions=True
		)
	except frappe.UniqueValidationError:
		pass
	return {"shortlisted": True}


def remove_from_shortlist(partner):
	customer = get_customer_for_user()
	if not customer:
		frappe.throw("Your account isn't linked to a customer company yet.", frappe.PermissionError)
	existing = frappe.db.get_value("Shortlist", {"customer": customer, "partner": partner})
	if existing:
		frappe.delete_doc("Shortlist", existing, ignore_permissions=True)
	return {"shortlisted": False}


def list_my_shortlist():
	"""Full Partner records the current user's company has shortlisted — backs the Shortlisted page."""
	customer = get_customer_for_user()
	if not customer:
		return []
	rows = frappe.get_all(
		"Shortlist", filters={"customer": customer}, fields=["partner"], order_by="creation desc"
	)
	names = [r.partner for r in rows]
	if not names:
		return []

	partners = frappe.get_list("Partner", fields=PARTNER_FIELDS, filters={"name": ["in", names]})
	by_name = {p.name: p for p in partners}
	ordered = [by_name[n] for n in names if n in by_name]

	apps_by_partner = _apps_by_partner(names)
	for p in ordered:
		p["apps_preview"] = apps_by_partner.get(p.name, [])[:2]

	attach_success_story_previews(ordered)
	return ordered
