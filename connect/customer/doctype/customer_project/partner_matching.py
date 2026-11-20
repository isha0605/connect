# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

from collections import Counter

import frappe

from connect.partner.doctype.partner.partner import (
	BASE_PARTNER_FILTERS,
	_partners_matching_child,
)
from connect.partner.doctype.partner_tier.partner_tier import get_tier_order
from connect.partner.industries import partners_in_industries

# Which partners the brief goes to. Each group narrows to any of the picked values; nothing
# picked means no limit there.
PARTNER_FIELDS = {"countries": "country", "cities": "city", "tiers": "tier"}
# Criteria groups, in the order the chips show; industries and apps match the partners' picked
# ones, and a partner with any one of the picked apps matches.
CRITERIA_GROUPS = ("countries", "industries", "apps", "cities", "tiers")


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
	in_reach = normalize_criteria(
		{"countries": criteria["countries"], "industries": criteria["industries"], "apps": criteria["apps"]}
	)
	partners = frappe.get_all("Partner", filters=get_partner_filters(in_reach), fields=["name", "city", "tier"])

	cities = Counter(p.city for p in partners if p.city)
	tiers = Counter(p.tier for p in partners if p.tier)

	return {
		"cities": [{"value": city, "count": count} for city, count in sorted(cities.items())],
		"tiers": [{"value": tier, "count": tiers[tier]} for tier in get_tier_order() if tier in tiers],
		"total": frappe.db.count("Partner", get_partner_filters(criteria)),
	}


def _recipient_cards(criteria: dict) -> list[dict]:
	partners = frappe.get_all(
		"Partner",
		filters=_recipient_filters(criteria),
		fields=["name", "company_name", "logo", "logo_icon"],
		order_by="company_name asc",
	)
	return [
		{"name": p.name, "company_name": p.company_name or p.name, "logo": p.logo_icon or p.logo}
		for p in partners
	]


def _recipient_filters(criteria: dict) -> list:
	"""Matching partners that have an Owner to read the brief."""
	with_admin = frappe.get_all(
		"Connect Partner Member", filters={"access": "Owner", "is_removed": 0}, pluck="partner", distinct=True
	)
	return [*get_partner_filters(criteria), ["Partner", "name", "in", with_admin or [""]]]


def get_partner_filters(criteria: dict) -> list:
	"""`frappe.get_all` filters for the listed partners that match normalized `criteria`."""
	filters = list(BASE_PARTNER_FILTERS)
	for group, field in PARTNER_FIELDS.items():
		if criteria[group]:
			filters.append(["Partner", field, "in", criteria[group]])
	if criteria["industries"]:
		filters.append(["Partner", "name", "in", list(partners_in_industries(criteria["industries"])) or [""]])
	if criteria["apps"]:
		with_apps = _partners_matching_child("Partner App", "app", "in", criteria["apps"], parentfield="apps")
		filters.append(["Partner", "name", "in", list(with_apps) or [""]])
	return filters


def normalize_criteria(criteria: dict | None) -> dict:
	criteria = criteria or {}
	return {group: [value for value in criteria.get(group) or [] if value] for group in CRITERIA_GROUPS}
