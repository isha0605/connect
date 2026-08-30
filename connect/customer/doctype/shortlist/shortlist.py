# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Shortlist(Document):
	def validate(self):
		duplicate = frappe.db.exists(
			"Shortlist",
			{"customer": self.customer, "partner": self.partner, "name": ["!=", self.name]},
		)
		if duplicate:
			frappe.throw(f"{self.partner} is already shortlisted for {self.customer}.")

	def before_insert(self):
		from connect.customer.doctype.customer.customer import get_customer_for_user
		if not self.customer:
			self.customer = get_customer_for_user()
		if not self.customer:
			frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)


def _customer_names_for_user(user):
	return frappe.get_all("Customer Team Member", filters={"user": user}, pluck="parent")


def get_permission_query_conditions(user):
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return ""
	customers = _customer_names_for_user(user)
	if not customers:
		return "1=0"
	names = ", ".join(frappe.db.escape(c) for c in customers)
	return f"`tabShortlist`.customer in ({names})"


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
	from connect.customer.doctype.customer.customer import get_customer_for_user
	customer = get_customer_for_user()
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)
	if not frappe.db.exists("Shortlist", {"customer": customer, "partner": partner}):
		frappe.get_doc({"doctype": "Shortlist", "customer": customer, "partner": partner}).insert(
			ignore_permissions=True
		)
		frappe.db.commit()
	return {"shortlisted": True}


def remove_from_shortlist(partner: str):
	from connect.customer.doctype.customer.customer import get_customer_for_user
	customer = get_customer_for_user()
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)
	existing = frappe.db.get_value("Shortlist", {"customer": customer, "partner": partner})
	if existing:
		frappe.delete_doc("Shortlist", existing, ignore_permissions=True)
		frappe.db.commit()
	return {"shortlisted": False}


def list_my_shortlist():
	"""Full Partner records the current user's company has shortlisted — backs the Shortlisted page."""
	from connect.customer.doctype.customer.customer import get_customer_for_user
	from connect.partner.doctype.partner.partner import PARTNER_FIELDS
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

	apps_by_partner = {}
	for row in frappe.get_all(
		"Partner App", filters={"parent": ["in", names]}, fields=["parent", "app"], order_by="idx asc"
	):
		bucket = apps_by_partner.setdefault(row.parent, [])
		if len(bucket) < 2:
			bucket.append(row.app)
	for p in ordered:
		p["apps_preview"] = apps_by_partner.get(p.name, [])

	success_stories_by_partner = {}
	for row in frappe.get_all(
		"Partner Success Story",
		filters={"parent": ["in", names]},
		fields=["parent", "category"],
		order_by="idx asc",
	):
		bucket = success_stories_by_partner.setdefault(row.parent, {"count": 0, "categories": []})
		bucket["count"] += 1
		if row.category and row.category not in bucket["categories"]:
			bucket["categories"].append(row.category)
	for p in ordered:
		stories = success_stories_by_partner.get(p.name, {"count": 0, "categories": []})
		p["success_story_count"] = stories["count"]
		p["success_story_categories"] = stories["categories"]

	return ordered
