# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import Order


class Requirement(Document):
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
	RequirementTable = frappe.qb.DocType("Requirement")
	return RequirementTable.customer.isin(customers).get_sql()


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

	return {"name": doc.name}


REQUIREMENT_FIELDS = [
	"name", "company_name", "country", "industry", "looking_for", "company_size",
	"current_situation", "timeline", "delivery_preference", "budget",
	"special_requirements", "additional_notes",
]


def _latest_requirement_for_customer(customer):
	"""The customer's most recent Requirement — just the fields
	get_my_requirement/get_requirement_snapshot actually return, plus its apps,
	in 2 queries total (one row + one child-table fetch). frappe.get_doc(...)
	would do this in more queries for less: one SELECT * for every column on
	the doctype (not just the ~12 we use) plus one query per child table the
	doctype defines, whether we read it or not."""
	RequirementTable = frappe.qb.DocType("Requirement")
	rows = (
		frappe.qb.from_(RequirementTable)
		.select(*[RequirementTable[f] for f in REQUIREMENT_FIELDS])
		.where(RequirementTable.customer == customer)
		.orderby(RequirementTable.creation, order=Order.desc)
		.limit(1)
		.run(as_dict=True)
	)
	if not rows:
		return None
	req = rows[0]

	AppTable = frappe.qb.DocType("Partner App")
	req["apps"] = (
		frappe.qb.from_(AppTable)
		.select(AppTable.app)
		.where(
			(AppTable.parent == req.name)
			& (AppTable.parenttype == "Requirement")
			& (AppTable.parentfield == "apps")
		)
		.orderby(AppTable.idx)
		.run(pluck=True)
	)
	return req


def get_my_requirement():
	"""The current user's company's saved requirement, for prefilling the Settings
	"Edit Requirements" form — None if they haven't saved one yet (add mode), and
	for a logged-out visitor (same as no customer link)."""
	from connect.customer.doctype.customer.customer import get_customer_for_user
	customer = get_customer_for_user()
	if not customer:
		return None
	req = _latest_requirement_for_customer(customer)
	if not req:
		return None
	return {
		"name": req.name,
		"company_name": req.company_name,
		"country": req.country,
		"industry": req.industry,
		"apps": req.apps,
		"looking_for": req.looking_for,
		"company_size": req.company_size,
		"current_situation": req.current_situation,
		"timeline": req.timeline,
		"delivery_preference": req.delivery_preference,
		"budget": req.budget,
		"special_requirements": req.special_requirements,
		"additional_notes": req.additional_notes,
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
	req = _latest_requirement_for_customer(customer)
	if not req:
		return None
	return {
		"company_name": req.company_name,
		"country": req.country,
		"industry": req.industry,
		"apps": req.apps,
		"looking_for": req.looking_for,
		"company_size": req.company_size,
		"current_situation": req.current_situation,
		"timeline": req.timeline,
		"delivery_preference": req.delivery_preference,
		"budget": req.budget,
		"special_requirements": req.special_requirements,
		"additional_notes": req.additional_notes,
	}
