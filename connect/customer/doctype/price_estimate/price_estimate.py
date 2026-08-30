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

	base_price = 0
	if pack_type:
		base_price = frappe.db.get_value("Partner Pack", {"parent": partner, "pack_name": pack_type}, "price") or 0

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
	return doc.name


def get_pricing_view(partner: str, requirement: str | None = None):
	"""Drives the Partner Profile Pricing tab. Guest-safe like the rest of the
	profile page — a logged-out visitor or one with no saved Requirement simply
	lands on "no_requirement", same honest fallback either way."""
	from connect.customer.doctype.customer.customer import get_customer_for_user
	from connect.partner.doctype.partner.partner import _pack_is_primary_match
	if not partner or partner == "undefined" or not frappe.db.exists("Partner", partner):
		return {"state": "loading"}

	partner_info = frappe.db.get_value("Partner", partner, ["starter_pack", "hourly_rate"], as_dict=True)
	hourly_rate = flt(partner_info.hourly_rate)
	addons = frappe.get_all("Partner Addon", filters={"parent": partner}, fields=["*"], order_by="idx")
	addon_rate = 2000 if partner_info.starter_pack else hourly_rate

	if not requirement:
		customer = get_customer_for_user()
		if customer:
			requirement = frappe.db.get_value(
				"Requirement", {"customer": customer}, "name", order_by="creation desc"
			)

	if not partner_info.starter_pack:
		return {
			"state": "hourly_only", "rate": hourly_rate,
			"addons": addons, "addon_rate": addon_rate, "requirement": requirement,
		}

	if not requirement:
		return {"state": "no_requirement", "rate": hourly_rate, "addons": addons, "addon_rate": addon_rate}

	req_apps = frappe.get_all(
		"Partner App",
		filters={"parent": requirement, "parenttype": "Requirement", "parentfield": "apps"},
		pluck="app",
		order_by="idx",
	)
	has_erpnext = "ERPNext" in req_apps
	has_hr = "Frappe HR" in req_apps

	if not (has_erpnext or has_hr):
		return {
			"state": "mismatch",
			"rate": hourly_rate,
			"requested_product": ", ".join(req_apps) if req_apps else None,
			"requirement": requirement,
			"addons": addons,
			"addon_rate": addon_rate,
		}

	packs = frappe.get_all("Partner Pack", filters={"parent": partner}, fields=["*"], order_by="idx")
	for p in packs:
		p["is_primary_match"] = _pack_is_primary_match(p["pack_key"], has_erpnext, has_hr)

	return {
		"state": "eligible",
		"packs": packs,
		"addons": addons,
		"requirement": requirement,
	}
