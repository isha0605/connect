# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

from collections import Counter

import frappe

from connect.customer.doctype.customer_project.answers import answer_label
from connect.partner.doctype.partner.partner import (
	BASE_PARTNER_FILTERS,
	_child_values_by_partner,
	_partners_matching_child,
)

# Which partners the brief goes to ("Edit criteria" on the custom implementation page).
# Each group narrows to any of the picked values; nothing picked means no limit there.
# "How do you want to work" maps onto the partners' delivery modes, where Hybrid counts
# for both. The go-live answer is edited alongside but doesn't filter partners.
WORK_MODES = {"onsite": ("Onsite", "Hybrid"), "remote": ("Remote", "Hybrid")}
PARTNER_FIELDS = {"countries": "country", "industries": "industry", "cities": "city", "tiers": "tier"}


def partner_criteria(criteria: str | dict | None = None, include_recipients: bool = False) -> dict:
	"""The Edit criteria chips with how many partners each covers, and how many match the
	given criteria. Chip counts are per option on their own, among the partners in the
	chosen countries and industries (what the questions answered). With `include_recipients`,
	a signed-in caller also gets the partners the brief would be sent to."""
	criteria = normalize_criteria(frappe.parse_json(criteria) or {})
	facets = _criteria_facets(criteria)
	if include_recipients and frappe.session.user != "Guest":
		facets["recipients"] = _recipient_cards(criteria)
	return facets


def get_brief_recipients(criteria: dict) -> list[str]:
	return frappe.get_all("Partner", filters=_recipient_filters(criteria), pluck="name")


def _criteria_facets(criteria: dict) -> dict:
	in_reach = normalize_criteria({"countries": criteria["countries"], "industries": criteria["industries"]})
	partners = frappe.get_all("Partner", filters=get_partner_filters(in_reach), fields=["name", "city", "tier"])
	modes = _child_values_by_partner(
		"Partner Delivery Mode", "delivery_mode", [p.name for p in partners], parentfield="delivery_options"
	)

	cities = Counter(p.city for p in partners if p.city)
	tiers = Counter(p.tier for p in partners if p.tier)
	tier_order = frappe.get_meta("Partner").get_options("tier").split("\n")

	return {
		"cities": [{"value": city, "count": count} for city, count in sorted(cities.items())],
		"tiers": [{"value": tier, "count": tiers[tier]} for tier in tier_order if tier in tiers],
		"work": [
			{
				"value": key,
				"label": answer_label("work", key),
				"count": sum(1 for p in partners if set(modes.get(p.name, ())) & set(wanted)),
			}
			for key, wanted in WORK_MODES.items()
		],
		"total": frappe.db.count("Partner", get_partner_filters(criteria)),
	}


def _recipient_cards(criteria: dict) -> list[dict]:
	partners = frappe.get_all(
		"Partner",
		filters=_recipient_filters(criteria),
		fields=["name", "partner_name", "logo", "logo_icon"],
		order_by="partner_name asc",
	)
	return [
		{"name": p.name, "partner_name": p.partner_name or p.name, "logo": p.logo_icon or p.logo}
		for p in partners
	]


def _recipient_filters(criteria: dict) -> list:
	"""Matching partners that have an admin to read the brief."""
	with_admin = frappe.get_all("Connect Partner Member", filters={"is_admin": 1}, pluck="partner", distinct=True)
	return [*get_partner_filters(criteria), ["Partner", "name", "in", with_admin or [""]]]


def get_partner_filters(criteria: dict) -> list:
	"""`frappe.get_all` filters for the listed partners that match normalized `criteria`."""
	filters = list(BASE_PARTNER_FILTERS)
	for group, field in PARTNER_FIELDS.items():
		if criteria[group]:
			filters.append(["Partner", field, "in", criteria[group]])

	if criteria["work"]:
		wanted = {mode for work in criteria["work"] for mode in WORK_MODES[work]}
		working = _partners_matching_child(
			"Partner Delivery Mode", "delivery_mode", "in", list(wanted), parentfield="delivery_options"
		)
		filters.append(["Partner", "name", "in", list(working) or [""]])
	return filters


def normalize_criteria(criteria: dict | None) -> dict:
	criteria = criteria or {}
	normalized = {group: [value for value in criteria.get(group) or [] if value] for group in PARTNER_FIELDS}
	normalized["work"] = [work for work in criteria.get("work") or [] if work in WORK_MODES]
	return normalized
