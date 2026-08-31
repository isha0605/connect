# Copyright (c) 2026
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from connect.customer.doctype.customer.customer import get_customer_for_user


class PriceEstimate(Document):
	pass


# Which packs are the "closest fit" for a given requirement's product interest,
# derived from Requirement.apps (there's no dedicated product_interest field —
# apps already carries this signal, since its options come from the real App
# doctype and already include "ERPNext" and "Frappe HR").
def _pack_is_primary_match(pack_key, has_erpnext, has_hr):
	if pack_key == "allinone":
		return has_erpnext and has_hr
	if pack_key in ("core", "manufacturing"):
		return has_erpnext and not has_hr
	if pack_key == "hr":
		return has_hr and not has_erpnext
	return False


def get_pricing_view(partner, requirement=None):
	"""Returns pricing info for the Partner Profile Pricing tab, based on the partner's plans and the caller's saved requirement."""
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


def save_price_estimate(partner, selected_addons, total, requirement=None, pack_type=None):
	"""Saves a customer's price estimate (pack plus add-ons) at the moment they contact the partner about it."""
	customer = get_customer_for_user()
	if not customer:
		frappe.throw("Your account isn't linked to a customer company yet.", frappe.PermissionError)

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
