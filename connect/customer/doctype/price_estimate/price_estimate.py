# Copyright (c) 2026
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint


class PriceEstimate(Document):
	pass


def save_price_estimate(
	partner: str,
	selected_addons: str | list,
	total: float,
	requirement: str | None = None,
	pack_type: str | None = None,
):
	"""Record a customer's starter-pack estimate (pack + selected add-ons) at the
	moment they choose to contact the partner about it, so the partner sees
	exactly what was being estimated rather than a blind inquiry. requirement/
	pack_type are optional — the no_requirement and mismatch pricing states have
	no eligible pack, only an hourly-rate add-on estimate, so base_price is 0 and
	pack_type stays blank for those."""
	from connect.customer.doctype.customer.customer import get_customer_for_user
	customer = get_customer_for_user()
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)

	if isinstance(selected_addons, str):
		selected_addons = json.loads(selected_addons or "[]")

	partner_doc = frappe.get_doc("Partner", partner)
	base_price = next((p.price for p in partner_doc.packs if p.pack_name == pack_type), 0)

	doc = frappe.get_doc({
		"doctype": "Price Estimate",
		"user": frappe.session.user,
		"partner": partner,
		"requirement": requirement,
		"pack_type": pack_type,
		"base_price": base_price,
		"total": flt(total),
	})
	for addon in selected_addons:
		doc.append("selected_options", {"feature_name": addon.get("name"), "price": addon.get("price")})
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def get_pricing_view(partner: str, requirement: str | None = None):
	"""Drives the Partner Profile Pricing tab. Guest-safe like the rest of the
	profile page — a logged-out visitor or one with no saved Requirement simply
	lands on "no_requirement", same honest fallback either way."""
	from connect.customer.doctype.customer.customer import get_customer_for_user
	from connect.partner.doctype.partner.partner import _pack_is_primary_match
	if not partner or partner == "undefined" or not frappe.db.exists("Partner", partner):
		return {"state": "loading"}

	partner_doc = frappe.get_doc("Partner", partner)
	addons = [a.as_dict() for a in partner_doc.addons]
	addon_rate = 2000 if partner_doc.starter_pack else flt(partner_doc.hourly_rate)

	if not requirement:
		customer = get_customer_for_user()
		if customer:
			requirement = frappe.db.get_value(
				"Requirement", {"customer": customer}, "name", order_by="creation desc"
			)

	if not partner_doc.starter_pack:
		return {
			"state": "hourly_only", "rate": partner_doc.hourly_rate,
			"addons": addons, "addon_rate": addon_rate, "requirement": requirement,
		}

	if not requirement:
		return {"state": "no_requirement", "rate": partner_doc.hourly_rate, "addons": addons, "addon_rate": addon_rate}

	req = frappe.get_doc("Requirement", requirement)
	req_apps = [a.app for a in req.apps]
	has_erpnext = "ERPNext" in req_apps
	has_hr = "Frappe HR" in req_apps

	if not (has_erpnext or has_hr):
		return {
			"state": "mismatch",
			"rate": partner_doc.hourly_rate,
			"requested_product": ", ".join(req_apps) if req_apps else None,
			"requirement": req.name,
			"addons": addons,
			"addon_rate": addon_rate,
		}

	packs = [p.as_dict() for p in partner_doc.packs]
	for p in packs:
		p["is_primary_match"] = _pack_is_primary_match(p["pack_key"], has_erpnext, has_hr)

	return {
		"state": "eligible",
		"packs": packs,
		"addons": addons,
		"requirement": req.name,
	}
