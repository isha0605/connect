# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document

from connect.customer.doctype.customer.customer import get_customer_for_user


class Requirement(Document):
	pass


# The forms send the sizes the recommendation quiz uses; company_size stores them with an en dash,
# as the Find Partners wizard always has.
COMPANY_SIZES = {"1-10": "1–10", "11-50": "11–50", "51-200": "51–200", "201-500": "201–500", "500+": "500+"}  # noqa: RUF001


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
	country, industry, apps=None,
	looking_for=None, company_size=None, current_situation=None, timeline=None, delivery_preference=None, budget=None,
	special_requirements=None, additional_notes=None, outcome=None,
):
	"""Creates or updates the caller's one Requirement, so the wizard and the Settings form share a single saved
	record. Only the fields given change: Settings asks about the company alone, and must keep the rest.
	company_name isn't a parameter here — it's already collected at signup (Customer.customer_name),
	so it's read from there instead of asking again. company_size takes the forms' values as well
	as the stored ones (see COMPANY_SIZES)."""
	customer = get_customer_for_user()
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)

	if isinstance(apps, str):
		apps = json.loads(apps or "[]")

	given = {
		"country": country,
		"industry": industry,
		"looking_for": looking_for,
		"company_size": COMPANY_SIZES.get(company_size, company_size),
		"current_situation": current_situation,
		"timeline": timeline,
		"delivery_preference": delivery_preference,
		"budget": budget,
		"special_requirements": special_requirements,
		"additional_notes": additional_notes,
		"outcome": outcome or None,
	}
	values = {field: value for field, value in given.items() if value is not None}
	if apps is not None:
		values["apps"] = [{"app": a} for a in apps]
	values["customer"] = customer
	values["company_name"] = frappe.db.get_value("Customer", customer, "customer_name")

	existing = frappe.db.get_value("Requirement", {"customer": customer}, "name", order_by="creation desc")
	if existing:
		doc = frappe.get_doc("Requirement", existing)
		doc.update(values)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "Requirement", **values})
		doc.insert(ignore_permissions=True)

	return {"name": doc.name}


COMPANY_DETAIL_FIELDS = ["company_size", "industry", "current_situation", "additional_notes"]


def save_company_details(customer, values):
	"""Sets just these fields on the customer's one Requirement, creating it if they have none,
	so what they told the Find Partners wizard or the Settings form stays as it was. Returns
	whether anything changed. A new Requirement is for India: Starter Packs only sell there."""
	values = {f: values.get(f) or "" for f in COMPANY_DETAIL_FIELDS}
	existing = frappe.db.get_value("Requirement", {"customer": customer}, "name", order_by="creation desc")
	if existing:
		doc = frappe.get_doc("Requirement", existing)
		if all((doc.get(f) or "") == v for f, v in values.items()):
			return False
		doc.update(values)
		doc.save(ignore_permissions=True)
		return True

	frappe.get_doc(
		{
			"doctype": "Requirement",
			"customer": customer,
			"company_name": frappe.db.get_value("Customer", customer, "customer_name"),
			"country": "India",
			"outcome": "Starter Pack",
			**values,
		}
	).insert(ignore_permissions=True)
	return True


REQUIREMENT_FIELDS = [
	"name", "company_name", "country", "industry", "looking_for", "company_size",
	"current_situation", "timeline", "delivery_preference", "budget",
	"special_requirements", "additional_notes",
]


def _latest_requirement_for_customer(customer):
	"""The customer's most recent Requirement row plus its apps, in 2 queries total — just the
	fields get_my_requirement/get_requirement_snapshot actually return. frappe.get_doc(...) would
	cost one query for every column on the doctype (not just the ~12 used here) plus one query per
	child table it defines, whether read or not."""
	RequirementTable = frappe.qb.DocType("Requirement")
	rows = (
		frappe.qb.from_(RequirementTable)
		.select(*[RequirementTable[f] for f in REQUIREMENT_FIELDS])
		.where(RequirementTable.customer == customer)
		.orderby(RequirementTable.creation, order=frappe.qb.desc)
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
	"""Returns the caller's saved Requirement to prefill the Settings "Edit Requirements" form."""
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
		"employees": {v: k for k, v in COMPANY_SIZES.items()}.get(req.company_size, req.company_size),
		"current_situation": req.current_situation,
		"timeline": req.timeline,
		"delivery_preference": req.delivery_preference,
		"budget": req.budget,
		"special_requirements": req.special_requirements,
		"additional_notes": req.additional_notes,
	}


def get_requirement_snapshot(customer=None):
	"""Returns the caller's (or the given customer's) saved Requirement as a dict, to seed a
	Requirement card in a new thread."""
	customer = customer or get_customer_for_user()
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
	}


def format_requirement_message(customer: str, note: str | None = None) -> str | None:
	"""Turns the customer's saved Requirement into a readable message body, with an optional note appended."""
	lines = []
	req = _latest_requirement_for_customer(customer)
	if req:
		lines.append(_("New inquiry from {0} — here's what they're looking for:").format(req.company_name or customer))
		if req.industry:
			lines.append(_("Industry: {0}").format(req.industry))
		if req.looking_for:
			lines.append(_("Looking for: {0}").format(req.looking_for))
		if req.apps:
			lines.append(_("Apps: {0}").format(", ".join(req.apps)))
		if req.company_size:
			lines.append(_("Company size: {0}").format(req.company_size))
		if req.timeline:
			lines.append(_("Timeline: {0}").format(req.timeline))
		if req.budget:
			lines.append(_("Budget: {0}").format(req.budget))
		if req.delivery_preference:
			lines.append(_("Delivery preference: {0}").format(req.delivery_preference))

	note = (note or "").strip()
	if note:
		if lines:
			lines.append("")
		lines.append(note)

	return "\n".join(lines) if lines else None
