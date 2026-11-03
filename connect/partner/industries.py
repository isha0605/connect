# Copyright (c) 2026, Isha and Contributors
# See license.txt

"""A partner's industries: the up to six they pick (Partner.industries), the verified tick their
success stories earn, and how businesses' industries match them. Industry names are frappe.io's
success-story categories, so a story's category and a picked industry compare as plain strings."""

from collections import Counter

import frappe
from frappe import _

MAX_INDUSTRIES = 6
# frappe.io's partner pages call an industry proven at this many published stories.
STORIES_FOR_TICK = 2


def picked_industries(doc) -> list[str]:
	return [row.industry for row in doc.get("industries") or [] if row.industry]


def validate_industries(doc) -> None:
	"""Called from Partner.validate."""
	picked = picked_industries(doc)
	if len(picked) > MAX_INDUSTRIES:
		frappe.throw(_("Pick up to {0} industries. You picked {1}.").format(MAX_INDUSTRIES, len(picked)))
	if len(set(picked)) != len(picked):
		frappe.throw(_("Each industry can be picked only once."))


def _story_counts(stories) -> Counter:
	return Counter((story.get("category") or "").strip() for story in stories or [] if story.get("category"))


def industry_badges(industries: list[str], stories) -> list[dict]:
	"""Each picked industry, with how many success stories back it and whether that earns the tick."""
	counts = _story_counts(stories)
	return [
		{"industry": industry, "stories": counts[industry], "verified": counts[industry] >= STORIES_FOR_TICK}
		for industry in industries
	]


def suggested_industries(industries: list[str], stories) -> list[dict]:
	"""Industries the partner's stories prove but they haven't picked, for the edit dialog to offer."""
	counts = _story_counts(stories)
	proven = [name for name, count in counts.most_common() if count >= STORIES_FOR_TICK and name not in industries]
	known = set(frappe.get_all("Industry", filters={"name": ["in", proven or [""]]}, pluck="name"))
	return [{"industry": name, "stories": counts[name]} for name in proven if name in known]


def expand_industries(names: list[str]) -> list[str]:
	"""The industries that count as a match for `names`: each one, its group, and, for a group, every
	industry under it. A partner who picked Manufacturing matches a business in Textile Manufacturing,
	and a business that answered Manufacturing matches a Textile Manufacturing partner."""
	names = [name for name in names or [] if name]
	if not names:
		return []
	groups = frappe.get_all("Industry", filters={"name": ["in", names]}, fields=["name", "industry_group"])
	members = frappe.get_all("Industry", filters={"industry_group": ["in", names]}, pluck="name")
	expanded = set(names) | {row.industry_group for row in groups if row.industry_group} | set(members)
	return sorted(expanded)


def partners_in_industries(names: list[str]) -> set[str]:
	"""Partners with at least one picked industry matching any of `names` (see expand_industries)."""
	from connect.partner.doctype.partner.partner import _partners_matching_child

	expanded = expand_industries(names)
	if not expanded:
		return set()
	return set(_partners_matching_child("Partner Industry", "industry", "in", expanded, parentfield="industries"))


def industries_by_partner(names: list[str]) -> dict[str, list[str]]:
	from connect.partner.doctype.partner.partner import _child_values_by_partner

	return _child_values_by_partner("Partner Industry", "industry", names, parentfield="industries")


def attach_industries(rows) -> list:
	"""Adds `industries` to each partner row, and `industry` (the first one) for the cards that
	still read a single industry ("Expertise in …")."""
	by_partner = industries_by_partner([row["name"] for row in rows])
	for row in rows:
		row["industries"] = by_partner.get(row["name"], [])
		row["industry"] = row["industries"][0] if row["industries"] else None
	return rows
