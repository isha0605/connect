# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.model.document import Document


class Requirement(Document):
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
	return f"`tabRequirement`.customer in ({names})"


def has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return True
	return doc.customer in _customer_names_for_user(user)


def save_customer_requirement(
	company_name: str,
	country: str,
	industry: str,
	apps: str | list | None = None,
	looking_for: str | None = None,
	company_size: str | None = None,
	current_situation: str | None = None,
	timeline: str | None = None,
	delivery_preference: str | None = None,
	budget: str | None = None,
	special_requirements: str | None = None,
	additional_notes: str | None = None,
	outcome: str | None = None,
):
	"""Create or update the current user's company's one Requirement — company_name/
	country/industry/apps are the 4 primary questions; everything else comes from
	the bundled, optional "Additional Requirements" step. Upserts by customer, so
	both the Find My Match wizard and the Settings "Edit Requirements" form share
	a single canonical requirement that either flow can fill in or update."""
	from connect.customer.doctype.customer.customer import get_customer_for_user
	customer = get_customer_for_user()
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)

	if isinstance(apps, str):
		apps = json.loads(apps or "[]")

	values = {
		"customer": customer,
		"company_name": company_name,
		"country": country,
		"industry": industry,
		"apps": [{"app": a} for a in (apps or [])],
		"looking_for": looking_for,
		"company_size": company_size,
		"current_situation": current_situation,
		"timeline": timeline,
		"delivery_preference": delivery_preference,
		"budget": budget,
		"special_requirements": special_requirements or "[]",
		"additional_notes": additional_notes or "",
	}
	if outcome:
		values["outcome"] = outcome

	existing = frappe.db.get_value("Requirement", {"customer": customer}, "name", order_by="creation desc")
	if existing:
		doc = frappe.get_doc("Requirement", existing)
		doc.update(values)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "Requirement", **values})
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
	return {"name": doc.name}


def get_my_requirement():
	"""The current user's company's saved requirement, for prefilling the Settings
	"Edit Requirements" form — None if they haven't saved one yet (add mode), and
	for a logged-out visitor (same as no customer link)."""
	from connect.customer.doctype.customer.customer import get_customer_for_user
	customer = get_customer_for_user()
	if not customer:
		return None
	name = frappe.db.get_value("Requirement", {"customer": customer}, "name", order_by="creation desc")
	if not name:
		return None
	doc = frappe.get_doc("Requirement", name)
	return {
		"name": doc.name,
		"company_name": doc.company_name,
		"country": doc.country,
		"industry": doc.industry,
		"apps": [a.app for a in doc.apps],
		"looking_for": doc.looking_for,
		"company_size": doc.company_size,
		"current_situation": doc.current_situation,
		"timeline": doc.timeline,
		"delivery_preference": doc.delivery_preference,
		"budget": doc.budget,
		"special_requirements": doc.special_requirements,
		"additional_notes": doc.additional_notes,
	}


def get_requirement_snapshot():
	"""The caller's most recently saved Requirement, as a plain dict of the fields a
	Requirement-type chat message card can show/edit — used to seed the composer's draft
	card on a fresh Contact-Partner thread (see start_partner_thread's `is_new_thread`).
	None if the caller isn't a customer or has no saved Requirement yet."""
	from connect.customer.doctype.customer.customer import get_customer_for_user
	customer = get_customer_for_user()
	if not customer:
		return None
	name = frappe.db.get_value("Requirement", {"customer": customer}, "name", order_by="creation desc")
	if not name:
		return None
	doc = frappe.get_doc("Requirement", name)
	return {
		"company_name": doc.company_name,
		"country": doc.country,
		"industry": doc.industry,
		"apps": [row.app for row in doc.apps],
		"looking_for": doc.looking_for,
		"company_size": doc.company_size,
		"current_situation": doc.current_situation,
		"timeline": doc.timeline,
		"delivery_preference": doc.delivery_preference,
		"budget": doc.budget,
		"special_requirements": doc.special_requirements,
		"additional_notes": doc.additional_notes,
	}
