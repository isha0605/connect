# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Shortlist(Document):
	def before_insert(self):
		from connect.customer.doctype.customer.customer import get_customer_for_user
		if not self.customer:
			self.customer = get_customer_for_user()
		if not self.customer:
			frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)


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
	"""Lightweight list of shortlisted partner names for the current user's company —
	used to mark bookmark state on Find Partners without re-fetching full partner rows."""
	from connect.customer.doctype.customer.customer import get_customer_for_user
	customer = get_customer_for_user()
	if not customer:
		return []
	return frappe.get_all("Shortlist", filters={"customer": customer}, pluck="partner")


def add_to_shortlist(partner: str):
	"""Idempotent: a second call for an already-shortlisted partner is a silent
	no-op rather than an error, matching the UI's bookmark-toggle semantics.
	Relies on the (customer, partner) unique constraint on Shortlist (see
	connect.patches.add_shortlist_unique_constraint) to reject a duplicate
	instead of checking for one first."""
	from connect.customer.doctype.customer.customer import get_customer_for_user
	customer = get_customer_for_user()
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)

	try:
		frappe.get_doc({"doctype": "Shortlist", "customer": customer, "partner": partner}).insert(
			ignore_permissions=True
		)
	except frappe.UniqueValidationError:
		pass
	return {"shortlisted": True}


def remove_from_shortlist(partner: str):
	from connect.customer.doctype.customer.customer import get_customer_for_user
	customer = get_customer_for_user()
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)

	ShortlistTable = frappe.qb.DocType("Shortlist")
	rows = (
		frappe.qb.from_(ShortlistTable)
		.select(ShortlistTable.name)
		.where((ShortlistTable.customer == customer) & (ShortlistTable.partner == partner))
		.run()
	)
	if rows:
		frappe.delete_doc("Shortlist", rows[0][0], ignore_permissions=True)
	return {"shortlisted": False}


def list_my_shortlist():
	"""Full Partner records the current user's company has shortlisted — backs the Shortlisted page."""
	from connect.customer.doctype.customer.customer import get_customer_for_user
	from connect.partner.doctype.partner.partner import PARTNER_FIELDS, _apps_by_partner, attach_success_story_previews
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
