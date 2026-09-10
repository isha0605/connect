# Copyright (c) 2026
# For license information, please see license.txt

import json
import math
from collections import Counter

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime, validate_email_address

from connect.partner.logo import attach_normalized_logos
from connect.partner.story_image import queue_missing_story_images
from connect.permissions import _my_company_membership

COUNTRY_TO_REGION = {
	"united states": "North America",
	"usa": "North America",
	"canada": "North America",
	"mexico": "North America",
	"united kingdom": "Europe",
	"uk": "Europe",
	"germany": "Europe",
	"france": "Europe",
	"netherlands": "Europe",
	"spain": "Europe",
	"italy": "Europe",
	"ireland": "Europe",
	"sweden": "Europe",
	"switzerland": "Europe",
	"india": "Asia Pacific",
	"china": "Asia Pacific",
	"japan": "Asia Pacific",
	"singapore": "Asia Pacific",
	"australia": "Asia Pacific",
	"new zealand": "Oceania",
	"indonesia": "Asia Pacific",
	"philippines": "Asia Pacific",
	"vietnam": "Asia Pacific",
	"malaysia": "Asia Pacific",
	"uae": "Middle East",
	"united arab emirates": "Middle East",
	"saudi arabia": "Middle East",
	"qatar": "Middle East",
	"israel": "Middle East",
	"south africa": "Africa",
	"nigeria": "Africa",
	"kenya": "Africa",
	"egypt": "Africa",
	"brazil": "Latin America",
	"argentina": "Latin America",
	"colombia": "Latin America",
	"chile": "Latin America",
}


DIMENSION_SCORE_FIELDS = (
	"business_understanding",
	"implementation_quality",
	"communication",
	"timeliness",
	"support",
	"technical_expertise",
)


class Partner(Document):
	def before_save(self):
		self.region = COUNTRY_TO_REGION.get((self.country or "").strip().lower(), "Other")

	def on_update(self):
		# background-fetches each success story's own frappe.io cover photo —
		# never blocks this save, and no-ops for rows that already have one
		queue_missing_story_images(self.get("success_stories"))


def recompute_rating_from_reviews(partner_name, exclude=None):
	"""Recomputes a Partner's rating and dimension scores from its Partner Review records."""
	filters = {"partner": partner_name}
	if exclude:
		filters["name"] = ["!=", exclude]
	reviews = frappe.get_all(
		"Partner Review",
		filters=filters,
		fields=["rating", *DIMENSION_SCORE_FIELDS],
	)

	values = {"rating": sum(flt(r.rating) for r in reviews) / len(reviews) if reviews else 0}

	for dimension in DIMENSION_SCORE_FIELDS:
		dim_values = [flt(r.get(dimension)) for r in reviews if r.get(dimension)]
		values[f"{dimension}_score"] = sum(dim_values) / len(dim_values) if dim_values else 0

	frappe.db.set_value("Partner", partner_name, values, update_modified=False)


PARTNER_FIELDS = [
	"name", "partner_name", "logo", "tagline", "tier", "specialist",
	"rating", "industry", "country", "city", "rollouts", "hourly_rate",
	"response_time_hours",
]
# The "is this partner visible at all" gate — combined as AND with whatever
# else a caller filters on. Callers that append more filters must copy this
# (list(BASE_PARTNER_FILTERS)) rather than mutate it in place.
BASE_PARTNER_FILTERS = [["Partner", "is_featured", "=", 1], ["Partner", "enabled", "=", 1]]


def _child_values_by_partner(child_doctype, value_field, names, parentfield=None):
	"""Every `value_field` value from `child_doctype` for each partner in `names`, in one query,
	grouped into a dict of lists keyed by partner name (full list, in idx order — callers wanting
	just a preview slice it themselves, e.g. apps[:2]). Always scoped to parenttype="Partner"; pass
	`parentfield` too for a child doctype shared with another doctype's own Table field (e.g.
	"Partner App" is also Requirement.apps) so a same-named parent from the other doctype can't
	leak in."""
	if not names:
		return {}
	filters = {"parent": ["in", names], "parenttype": "Partner"}
	if parentfield:
		filters["parentfield"] = parentfield
	values_by_partner = {}
	for r in frappe.get_all(child_doctype, filters=filters, fields=["parent", value_field], order_by="idx asc"):
		values_by_partner.setdefault(r.parent, []).append(r.get(value_field))
	return values_by_partner


def _apps_by_partner(names):
	"""Every Partner App (Partner.apps) value for each partner in `names` — see
	_child_values_by_partner. Kept as its own name since "apps per partner" is looked up from
	several places (search, wizard scoring, shortlist), not just the wizard scoring pass."""
	return _child_values_by_partner("Partner App", "app", names, parentfield="apps")


def _partners_matching_child(child_doctype, field, operator, value, parentfield=None):
	"""Names of partners with at least one `child_doctype` row satisfying `field <operator> value`
	— a WHERE name IN (subquery) membership check, not a join. Joining the child table directly
	onto Partner (Frappe's own ["<Child Doctype>", field, op, value] filter syntax does exactly
	that) multiplies a partner's row once per matching child row — combine two or more such
	filters at once (search_partners' filter panel lets you) and a partner with 2 matching rows in
	one child table and 3 in another comes back 6 times instead of once. A membership subquery is
	a plain yes/no test per partner, so it can't fan out no matter how many child rows exist."""
	ChildTable = frappe.qb.DocType(child_doctype)
	query = (
		frappe.qb.from_(ChildTable)
		.select(ChildTable.parent)
		.distinct()
		.where(ChildTable.parenttype == "Partner")
	)
	if parentfield:
		query = query.where(ChildTable.parentfield == parentfield)
	if operator == "=":
		query = query.where(ChildTable[field] == value)
	elif operator == "in":
		query = query.where(ChildTable[field].isin(value))
	elif operator == "is_set":
		query = query.where(ChildTable[field] != "")
	else:
		raise ValueError(f"Unsupported operator: {operator}")
	return {row[0] for row in query.run()}


def _parse_answers(answers):
	"""Normalizes the finder wizard's `answers` payload — arrives as a JSON string over the wire
	(a whitelisted endpoint's raw argument) but as a plain dict when one wizard function calls
	another directly in Python."""
	if isinstance(answers, str):
		answers = json.loads(answers or "{}")
	return answers or {}


def attach_success_story_previews(rows):
	"""Batch-attaches success_story_count/success_story_categories to each row in `rows` (each
	needs a "name" key matching a Partner document) — one query regardless of how many rows. Used
	everywhere a partner listing shows this preview: Find Partners search, the finder wizard's
	results, and the customer's Shortlisted page."""
	names = [r["name"] for r in rows]
	if not names:
		return rows
	buckets = {}
	for row in frappe.get_all(
		"Partner Success Story",
		filters={"parent": ["in", names], "parenttype": "Partner", "parentfield": "success_stories"},
		fields=["parent", "category"],
		order_by="idx asc",
	):
		bucket = buckets.setdefault(row.parent, {"count": 0, "categories": []})
		bucket["count"] += 1
		if row.category and row.category not in bucket["categories"]:
			bucket["categories"].append(row.category)
	for r in rows:
		stories = buckets.get(r["name"], {"count": 0, "categories": []})
		r["success_story_count"] = stories["count"]
		r["success_story_categories"] = stories["categories"]
	return rows


def _sqlite_rank(search_term, allowed_names):
	"""Ranks partner names by SQLite FTS5 relevance (with built-in spelling correction) against the
	search term, restricted to allowed_names — replaces the old MariaDB-only FULLTEXT MATCH/AGAINST
	ranking plus its difflib fuzzy-match fallback with connect.search.PartnerSearch, so this works
	regardless of the site's DB backend. allowed_names is passed as a `name` filter rather than
	baked into the index, since the structured filters (industry/region/child-table membership/etc.)
	already narrowed it in SQL before this ever runs — see search_partners."""
	if not allowed_names:
		return []
	from connect.search import PartnerSearch

	search = PartnerSearch()
	if not (search.is_search_enabled() and search.index_exists()):
		return []
	result = search.search(search_term, filters={"name": allowed_names})
	return [r["name"] for r in result["results"]]


SORT_OPTIONS = {
	"rating_desc": ("rating", True),
	"rollouts_desc": ("rollouts", True),
	"name_asc": ("partner_name", False),
}


# Operators the CRM-style Filter component can emit (its own WIRE_OPERATOR map) —
# validated against this whitelist before reaching the query.
FILTER_OPERATORS = {"is", "is not", "in", "not in", "=", "!=", "like", "not like", ">", "<", ">=", "<=", "between", "timespan"}


def search_partners(
	search=None, industry=None, product=None, region=None, delivery_mode=None, country=None,
	tier=None, business_process=None, implementation_type=None, language=None,
	category=None, exclude=None,
	min_rating=None, min_pmm_level=None, max_response_time=None,
	extra_filters=None,
	sort=None, limit=100,
):
	"""Searches partners for the Find Partners page, combining structured filters with full-text and fuzzy search."""
	# TEMPORARY: only surface the original curated (fully-profiled) partners
	# while the rest of the bulk-imported directory is still bare (name/tier/
	# country only, no logo/description/team). Remove this filter to bring the
	# full directory back — is_featured stays set on the underlying records.
	filters = list(BASE_PARTNER_FILTERS)
	for value, field in [
		(industry, "industry"), (region, "region"), (country, "country"), (tier, "tier"),
	]:
		if value:
			filters.append(["Partner", field, "=", value])

	# Child-table filters resolve via a membership subquery (_partners_matching_child), not
	# Frappe's built-in child-table join filter syntax — combining 2+ such filters as native join
	# tuples multiplies a partner's row once per matching child row on each side.
	child_matches = []
	for value, doctype, field, parentfield in [
		(product, "Partner App", "app", "apps"),
		(delivery_mode, "Partner Delivery Mode", "delivery_mode", None),
		(business_process, "Partner Business Process", "business_process", None),
		(implementation_type, "Partner Implementation Type", "implementation_type", None),
		(language, "Partner Language", "language", None),
		(category, "Partner Success Story", "category", "success_stories"),
	]:
		if value:
			child_matches.append(_partners_matching_child(doctype, field, "=", value, parentfield=parentfield))
	if child_matches:
		filters.append(["Partner", "name", "in", list(set.intersection(*child_matches))])

	if exclude:
		filters.append(["Partner", "name", "not in", list(exclude)])

	if min_rating not in (None, ""):
		filters.append(["Partner", "rating", ">=", flt(min_rating)])
	if min_pmm_level not in (None, ""):
		filters.append(["Partner", "pmm_level", ">=", flt(min_pmm_level)])
	if max_response_time not in (None, ""):
		filters.append(["Partner", "response_time_hours", "<=", cint(max_response_time)])

	if extra_filters:
		conditions = json.loads(extra_filters) if isinstance(extra_filters, str) else extra_filters
		meta = frappe.get_meta("Partner")
		valid_fieldnames = {f.fieldname for f in meta.fields} | {"name", "owner", "modified_by", "creation", "modified"}
		for condition in conditions:
			if len(condition) != 3:
				continue
			fieldname, operator, value = condition
			if fieldname not in valid_fieldnames or operator not in FILTER_OPERATORS:
				continue
			filters.append(["Partner", fieldname, operator, value])

	limit = cint(limit) or 100
	search = (search or "").strip()

	if not search:
		order_by = "rating desc"
		if sort in SORT_OPTIONS:
			field, desc = SORT_OPTIONS[sort]
			order_by = f"{field} {'desc' if desc else 'asc'}"
		partners = frappe.get_list(
			"Partner", fields=PARTNER_FIELDS, filters=filters, order_by=order_by, limit_page_length=limit
		)
	else:
		# Candidates passing the structured filters — unranked, no text match yet.
		# limit_page_length=0 is required here: frappe.get_list defaults to a page
		# size of 20 when omitted, which would silently truncate ranking input.
		candidates = frappe.get_list("Partner", fields=PARTNER_FIELDS, filters=filters, limit_page_length=0)
		by_name = {c.name: c for c in candidates}

		ranked_names = _sqlite_rank(search, list(by_name))
		ordered = [by_name[n] for n in ranked_names]

		# Candidates the FTS pass didn't rank at all (no match, even with spelling
		# correction) fall through unranked rather than being dropped.
		ordered += [c for c in candidates if c.name not in set(ranked_names)]

		partners = ordered[:limit]
		if sort in SORT_OPTIONS:
			field, desc = SORT_OPTIONS[sort]

			def sort_key(p, field=field, desc=desc):
				val = p.get(field)
				if val is None:
					return (1, 0)
				return (0, -val if desc else val)

			partners.sort(key=sort_key)

	partner_names = [p.name for p in partners]
	apps_by_partner = _apps_by_partner(partner_names)
	for p in partners:
		p["apps_preview"] = apps_by_partner.get(p.name, [])[:2]

	attach_success_story_previews(partners)
	return partners


# The finder wizard's industry options don't share the same value set as
# Partner.industry (different taxonomy, written for customers rather than
# partner classification) — translate to the closest Partner industry value.
WIZARD_TO_PARTNER_INDUSTRY = {
	"Manufacturing": "Manufacturing",
	"Retail & Distribution": "Retail",
	"Healthcare": "Healthcare",
	"Education": "Education",
	"Services": "Professional Services",
	"Construction": "Other",
	"Logistics": "Logistics",
	"Technology": "Technology",
	"Other": "Other",
}


# Real, defensible mappings from the wizard's customer-facing answers to Partner
# classification data. Deliberately partial — an answer with no clean equivalent
# (company size, timeline, budget, several "looking for" / "current situation"
# values) is left unmapped rather than guessed at, so the live count only ever
# narrows on a real signal.
LOOKING_FOR_TO_IMPL_TYPE = {
	"New ERP Implementation": "New Implementation",
	"Replace Existing ERP": "Migration",
	"Custom App Development": "Customization",
}
CURRENT_SITUATION_TO_MIGRATION = {
	"Tally": "Tally to ERPNext",
	"SAP": "SAP to ERPNext",
	"Odoo": "Odoo to ERPNext",
}
CURRENT_SITUATION_TO_IMPL_TYPE = {
	"Excel / Spreadsheets": "New Implementation",
	"No System Yet": "New Implementation",
	"Existing ERPNext": "Support & Maintenance",
}
DELIVERY_TO_MODE = {"Remote": "Remote", "Hybrid": "Hybrid", "On-site": "Onsite"}
REQUIREMENT_TO_BUSINESS_PROCESS = {
	"HR & Payroll": "HR & Payroll",
	"Manufacturing Planning": "Manufacturing Execution",
	"Inventory Management": "Inventory Management",
}
REQUIREMENT_MIGRATION_TAGS = {"SAP Migration", "Data Migration"}


def count_matching_partners(answers=None):
	"""Returns a live count of partners matching the finder wizard's answers so far, for the wizard's dot-grid."""
	answers = _parse_answers(answers)
	# Same temporary is_featured scope as search_partners, so the wizard's live
	# count never exceeds what the directory actually shows right now.
	filters = list(BASE_PARTNER_FILTERS)

	industry = answers.get("industry")
	if industry:
		filters.append(["Partner", "industry", "=", WIZARD_TO_PARTNER_INDUSTRY.get(industry, industry)])

	# Same membership-subquery approach as search_partners — see _partners_matching_child.
	child_matches = []

	impl_type = LOOKING_FOR_TO_IMPL_TYPE.get(answers.get("looking_for"))
	if impl_type:
		child_matches.append(
			_partners_matching_child("Partner Implementation Type", "implementation_type", "=", impl_type)
		)

	situation = answers.get("current_situation")
	migration = CURRENT_SITUATION_TO_MIGRATION.get(situation)
	if migration:
		child_matches.append(_partners_matching_child("Partner Migration Path", "migration_path", "=", migration))
	else:
		impl_type_2 = CURRENT_SITUATION_TO_IMPL_TYPE.get(situation)
		if impl_type_2:
			child_matches.append(
				_partners_matching_child("Partner Implementation Type", "implementation_type", "=", impl_type_2)
			)

	mode = DELIVERY_TO_MODE.get(answers.get("delivery_preference"))
	if mode:
		child_matches.append(_partners_matching_child("Partner Delivery Mode", "delivery_mode", "=", mode))

	requirements = answers.get("requirements") or []
	bp_values = [REQUIREMENT_TO_BUSINESS_PROCESS[r] for r in requirements if r in REQUIREMENT_TO_BUSINESS_PROCESS]
	if bp_values:
		child_matches.append(
			_partners_matching_child("Partner Business Process", "business_process", "in", bp_values)
		)
	elif any(r in REQUIREMENT_MIGRATION_TAGS for r in requirements):
		child_matches.append(_partners_matching_child("Partner Migration Path", "migration_path", "is_set", None))

	if child_matches:
		filters.append(["Partner", "name", "in", list(set.intersection(*child_matches))])

	# limit_page_length=0: frappe.get_list defaults to page size 20 when omitted.
	partners = frappe.get_list("Partner", filters=filters, fields=["name"], limit_page_length=0)
	return len(partners)


def _score_partners_by_requirements(answers):
	"""Scores every featured partner by how many of the wizard's answered questions they fail to match, shared by wizard_match_state and list_matching_partners."""
	names = [n.name for n in frappe.get_list(
		"Partner", filters=BASE_PARTNER_FILTERS, fields=["name"], limit_page_length=0,
	)]
	if not names:
		return [], {}

	rows = frappe.get_list("Partner", filters=[["Partner", "name", "in", names]], fields=PARTNER_FIELDS)
	by_name = {r.name: r for r in rows}

	apps_by_partner = _apps_by_partner(names)
	delivery_by = _child_values_by_partner("Partner Delivery Mode", "delivery_mode", names)
	migrations_by = _child_values_by_partner("Partner Migration Path", "migration_path", names)
	impl_by = _child_values_by_partner("Partner Implementation Type", "implementation_type", names)
	bp_by = _child_values_by_partner("Partner Business Process", "business_process", names)

	industry = answers.get("industry")
	wanted_industry = WIZARD_TO_PARTNER_INDUSTRY.get(industry, industry) if industry else None

	delivery = answers.get("delivery_preference")
	wanted_mode = DELIVERY_TO_MODE.get(delivery) if delivery and delivery != "No preference" else None

	wanted_apps = answers.get("apps") or []

	looking_for = answers.get("looking_for")
	wanted_impl_type = LOOKING_FOR_TO_IMPL_TYPE.get(looking_for)

	situation = answers.get("current_situation")
	wanted_migration = CURRENT_SITUATION_TO_MIGRATION.get(situation)
	wanted_situation_impl_type = None if wanted_migration else CURRENT_SITUATION_TO_IMPL_TYPE.get(situation)

	requirements = answers.get("requirements") or []
	wanted_bps = [REQUIREMENT_TO_BUSINESS_PROCESS[r] for r in requirements if r in REQUIREMENT_TO_BUSINESS_PROCESS]
	wants_migration_tag = any(r in REQUIREMENT_MIGRATION_TAGS for r in requirements)

	# How many of the (up to 6) scored dimensions were actually answered — used by
	# list_matching_partners to scale its near-match tolerance. A flat "missing <= 2"
	# cap is generous when 8 questions were answered but makes almost the entire
	# featured pool look like a "near match" when only 2-3 were, which is exactly
	# the sparse-answers case a wizard reopen tends to produce (unset fields stay
	# unset unless the visitor deliberately fills them in).
	answered_dims = sum([
		bool(wanted_industry), bool(wanted_apps), bool(wanted_mode), bool(wanted_impl_type),
		bool(wanted_migration or wanted_situation_impl_type), bool(wanted_bps or wants_migration_tag),
	])

	all_scored = []
	for name in names:
		row = by_name.get(name)
		if not row:
			continue
		missing = []
		if wanted_industry and row.industry != wanted_industry:
			missing.append(f"{industry} Experience")
		if wanted_apps and not any(a in apps_by_partner.get(name, []) for a in wanted_apps):
			missing.append(", ".join(wanted_apps) + (" Support" if len(wanted_apps) == 1 else " support"))
		if wanted_mode and wanted_mode not in delivery_by.get(name, []):
			missing.append(f"{delivery} Delivery")
		if wanted_impl_type and wanted_impl_type not in impl_by.get(name, []):
			missing.append(f"{looking_for} Expertise")
		if wanted_migration and wanted_migration not in migrations_by.get(name, []):
			missing.append(f"{situation} Migration Experience")
		elif wanted_situation_impl_type and wanted_situation_impl_type not in impl_by.get(name, []):
			missing.append(f"{situation} Experience")
		if wanted_bps and not any(bp in bp_by.get(name, []) for bp in wanted_bps):
			missing.append(", ".join(requirements) + " Support")
		elif wants_migration_tag and not migrations_by.get(name):
			missing.append("Migration Experience")
		all_scored.append((len(missing), -(row.rating or 0), name, missing))

	all_scored.sort(key=lambda s: (s[0], s[1]))
	return all_scored, apps_by_partner, answered_dims


def wizard_match_state(answers=None):
	"""Returns exact-match partner names and count for the finder wizard's dot pictogram."""
	answers = _parse_answers(answers)

	all_scored, _apps_by_partner, _answered_dims = _score_partners_by_requirements(answers)
	exact = [s for s in all_scored if s[0] == 0]
	matched_names = [name for *_rest, name, _missing in exact]
	return {"matched_names": matched_names, "count": len(matched_names)}


def list_matching_partners(answers=None, limit=8):
	"""Returns ranked partner results for the finder wizard's final step, including close-but-imperfect matches."""
	answers = _parse_answers(answers)
	limit = cint(limit) or 8

	all_scored, apps_by_partner, answered_dims = _score_partners_by_requirements(answers)
	if not all_scored:
		return []

	best = all_scored[0][0]
	display_cap = max(best, math.ceil(answered_dims / 3)) if answered_dims else best
	scored = [s for s in all_scored if s[0] <= display_cap]

	names = [name for *_rest, name, _missing in scored]
	rows = frappe.get_list("Partner", filters=[["Partner", "name", "in", names]], fields=PARTNER_FIELDS)
	by_name = {r.name: r for r in rows}

	scored = scored[:limit]

	result = []
	for _missing_count, _neg_rating, name, missing in scored:
		row = dict(by_name[name])
		row["apps_preview"] = apps_by_partner.get(name, [])[:2]
		row["missing_label"] = ", ".join(missing) if missing else None
		result.append(row)

	attach_success_story_previews(result)
	return result


def region_presence_counts():
	"""Returns partner counts for the Find Partners redesign's region map, bucketed into the
	map's 6 regions (finer-grained than the Region select field — India is split out of Asia
	Pacific to match the map's own regions). Counts the full enabled directory, not just the
	is_featured-curated subset search_partners currently scopes to, since this is a presence
	overview rather than a list of profiles to show."""
	rows = frappe.get_all("Partner", fields=["country", "region"], filters={"enabled": 1})

	counts = {"india": 0, "asia": 0, "middle_east": 0, "africa": 0, "europe": 0, "americas": 0}
	for row in rows:
		if (row.country or "").strip().lower() == "india":
			counts["india"] += 1
		elif row.region == "Asia Pacific":
			counts["asia"] += 1
		elif row.region == "Middle East":
			counts["middle_east"] += 1
		elif row.region == "Africa":
			counts["africa"] += 1
		elif row.region == "Europe":
			counts["europe"] += 1
		elif row.region in ("North America", "Latin America"):
			counts["americas"] += 1
		# region "Oceania"/"Other" partners aren't represented in any of the map's 6 regions
	return counts


def _decorate_directory_rows(rows):
	"""Adds the review_count/success-story preview fields the directory card list needs on top of
	whatever search_partners already returned. Shared by list_directory_partners and the wizard
	hand-off (list_directory_partners_for_wizard) so both render identical cards."""
	names = [r.name for r in rows]
	review_partners = frappe.get_all("Partner Review", filters={"partner": ["in", names]}, pluck="partner") if names else []
	review_counts = Counter(review_partners)
	for row in rows:
		row["review_count"] = review_counts.get(row.name, 0)

	attach_success_story_previews(rows)
	return rows


def list_directory_partners(
	limit=9, search=None, tier=None, country=None, industry=None,
	business_process=None, implementation_type=None, language=None,
	min_rating=None, max_response_time=None,
):
	"""Returns featured partners (name, logo, tier, rating, rate, response time, success stories)
	for the Partner Directory redesign's card list and its filter row. Filtering/search/ordering is
	delegated to search_partners — the same engine behind the Find Partners page — so both stay
	consistent; this only adds the review_count/success-story preview fields the card list needs on
	top, same as before this had its own filters."""
	rows = search_partners(
		search=search, tier=tier, country=country, industry=industry,
		business_process=business_process, implementation_type=implementation_type, language=language,
		min_rating=min_rating, max_response_time=max_response_time,
		limit=cint(limit) or 9,
	)
	return _decorate_directory_rows(rows)


def list_directory_partners_for_wizard(industry=None, category=None, limit=9):
	"""Hands the Find Partners wizard's industry/segment answer off to the Partner Directory as a
	real filter, in one call: `matches` are partners filtered on both industry and the segment's
	success-story category; `fallback` are same-industry partners who don't have a published story
	in that specific category (dropping the category filter, excluding anyone already in `matches`)
	— the "Proven in other industries" section, so a narrow segment pick doesn't dead-end the page
	when no partner has that exact category yet."""
	matches = search_partners(industry=industry or None, category=category or None, limit=cint(limit) or 9)
	fallback = []
	if category:
		fallback = search_partners(
			industry=industry or None, exclude=[m.name for m in matches], limit=cint(limit) or 9,
		)
	return {
		"matches": _decorate_directory_rows(matches),
		"fallback": _decorate_directory_rows(fallback),
	}


def list_partner_tiers():
	"""Returns the tiers actually in use among directory-listed partners (same is_featured/enabled
	scope as list_directory_partners), in Gold/Silver/Bronze order, for the Tier filter dropdown."""
	rows = frappe.get_all("Partner", fields=["tier"], filters=BASE_PARTNER_FILTERS, distinct=True)
	present = {row.tier for row in rows if row.tier}
	tier_order = ["Gold", "Silver", "Bronze"]
	return [t for t in tier_order if t in present]


def list_partner_countries():
	"""Returns distinct countries with at least one partner, for the Country filter dropdown."""
	rows = frappe.get_all(
		"Partner", fields=["country"], filters={"country": ["is", "set"], "is_featured": 1, "enabled": 1}, distinct=True
	)
	return sorted({row.country for row in rows if row.country})


def list_partner_industries():
	"""Returns distinct industries actually in use among directory-listed partners (same
	is_featured/enabled scope as list_directory_partners), for the Industry filter dropdown —
	deliberately not the Partner.industry Select's full static option list, so a value with zero
	partners behind it (e.g. "Nonprofit") doesn't show up as a dead-end filter."""
	rows = frappe.get_all(
		"Partner", fields=["industry"], filters={"industry": ["is", "set"], "is_featured": 1, "enabled": 1}, distinct=True
	)
	return sorted({row.industry for row in rows if row.industry})


def list_partner_filter_options():
	"""Returns filter dropdown options as a plain API call, since Studio's Document List resource isn't guest-accessible."""
	return {
		"business_processes": frappe.get_all("Business Process", pluck="title", order_by="title"),
		"implementation_types": frappe.get_all("Implementation Type", pluck="title", order_by="title"),
		"languages": frappe.get_all("FC Language", pluck="title", order_by="title"),
		"apps": frappe.get_all("App", pluck="title", order_by="title"),
		"migration_paths": frappe.get_all("Migration Path", pluck="title", order_by="title"),
	}


def get_partner_preview(partner):
	"""Returns a lightweight partner snapshot for the quick-preview drawer, fetched only when needed."""
	fields = [
		"name", "partner_name", "logo", "description", "tier", "specialist",
		"rating", "city", "country", "pmm_level", "hourly_rate",
		"certs_erpnext", "certs_frappe_framework", "industry", "address",
	]
	doc = frappe.db.get_value("Partner", partner, fields, as_dict=True)
	if not doc:
		frappe.throw(_("Partner not found"), frappe.DoesNotExistError)

	doc["apps"] = _apps_by_partner([partner]).get(partner, [])
	doc["migrations"] = frappe.get_all(
		"Partner Migration Path", filters={"parent": partner}, pluck="migration_path", order_by="idx asc"
	)
	return doc


def _compute_display_industries(industry, success_stories):
	"""Industries to show under the profile's "Industry" tags: the manually-set primary
	industry, plus any success-story category with at least 2 published case studies —
	the same "prove it with case studies" bar frappe.io/partners itself uses to decide
	which industries a partner is shown as serving."""
	counts = {}
	for row in success_stories or []:
		category = (row.get("category") or "").strip()
		if category:
			counts[category] = counts.get(category, 0) + 1

	industries = []
	if industry:
		industries.append(industry)
	for category, count in counts.items():
		if count >= 2 and category not in industries:
			industries.append(category)
	return industries


def get_partner_document(partner):
	"""Returns the full Partner record as a plain API call, since Studio's Document resource isn't guest-accessible."""
	if not frappe.db.exists("Partner", partner):
		frappe.throw(_("Partner not found"), frappe.DoesNotExistError)
	doc = frappe.get_doc("Partner", partner).as_dict()
	# computed, not stored — "founded_years_ago" would silently go stale every
	# year if we persisted it instead of deriving it from year_founded on read
	doc["founded_years_ago"] = (
		now_datetime().year - doc["year_founded"] if doc.get("year_founded") else None
	)
	doc["display_industries"] = _compute_display_industries(doc.get("industry"), doc.get("success_stories"))
	# adds client_logo_display per success story — a greyscale-normalized copy of
	# the client logo where one has been built, else the original URL
	attach_normalized_logos(doc.get("success_stories"))
	return doc


def _my_partner():
	"""Resolves the caller's own Partner, throwing if they aren't on a partner's roster."""
	doctype, partner, _row = _my_company_membership(frappe.session.user)
	if doctype != "Connect Partner Member":
		frappe.throw(_("You are not a member of any partner company"), frappe.PermissionError)
	return partner


def _parse_json_arg(value, default):
	"""Whitelisted list/dict args arrive as JSON strings over the wire but as the parsed
	value already when called directly from Python — same shape `_parse_answers` handles."""
	if isinstance(value, str):
		return json.loads(value) if value else default
	return value if value is not None else default


ALLOWED_LOGO_EXTENSIONS = {
	".png": "image/png",
	".jpg": "image/jpeg",
	".jpeg": "image/jpeg",
	".gif": "image/gif",
	".webp": "image/webp",
	".svg": "image/svg+xml",
}
MAX_LOGO_SIZE = 5 * 1024 * 1024  # 5 MB


def upload_partner_logo():
	"""Sets the caller's own partner's logo from an uploaded image — public, since it's shown to customers."""
	import os

	partner = _my_partner()
	uploaded = frappe.request.files.get("file") if frappe.request else None
	if not uploaded:
		frappe.throw(_("No file was uploaded"))

	filename = uploaded.filename or ""
	ext = os.path.splitext(filename)[1].lower()
	if ext not in ALLOWED_LOGO_EXTENSIONS:
		frappe.throw(_("Only PNG, JPG, GIF, SVG, and WEBP images can be used as a logo"))

	content = uploaded.stream.read()
	if len(content) > MAX_LOGO_SIZE:
		frappe.throw(_("Image is too large — the limit is {0} MB").format(MAX_LOGO_SIZE // (1024 * 1024)))

	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": filename,
		"content": content,
		"is_private": 0,
		"attached_to_doctype": "Partner",
		"attached_to_name": partner,
		"attached_to_field": "logo",
	})
	file_doc.insert(ignore_permissions=True)

	frappe.db.set_value("Partner", partner, "logo", file_doc.file_url)
	return {"logo": file_doc.file_url}


def upload_partner_asset():
	"""Uploads an image for the caller's own partner without attaching it to a specific
	field — used for things like the founder's photo, which lives on a "team" child row that
	may not exist yet (a new partner has no team members), so there's no stable doctype/name
	to attach a File to ahead of time. The caller stores the returned URL in whichever field
	it belongs to and it's persisted normally on the next profile save."""
	import os

	partner = _my_partner()
	uploaded = frappe.request.files.get("file") if frappe.request else None
	if not uploaded:
		frappe.throw(_("No file was uploaded"))

	filename = uploaded.filename or ""
	ext = os.path.splitext(filename)[1].lower()
	if ext not in ALLOWED_LOGO_EXTENSIONS:
		frappe.throw(_("Only PNG, JPG, GIF, SVG, and WEBP images can be uploaded"))

	content = uploaded.stream.read()
	if len(content) > MAX_LOGO_SIZE:
		frappe.throw(_("Image is too large — the limit is {0} MB").format(MAX_LOGO_SIZE // (1024 * 1024)))

	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": filename,
		"content": content,
		"is_private": 0,
		"attached_to_doctype": "Partner",
		"attached_to_name": partner,
	})
	file_doc.insert(ignore_permissions=True)

	return {"file_url": file_doc.file_url}


# Table MultiSelect fields where the frontend only ever sends the flat list of link values
# (matching what get_partner_document returns from _apps_by_partner-style helpers) — this maps
# each to the single non-standard fieldname on its child doctype so doc.set() gets proper rows.
_PROFILE_MULTISELECT_FIELDS = {
	"apps": "app",
	"migrations": "migration_path",
	"business_processes": "business_process",
	"implementation_types": "implementation_type",
	"languages": "language",
}

_PROFILE_SIMPLE_FIELDS = (
	# partner_name is deliberately excluded — it's the doc's autoname source (see
	# "autoname": "field:partner_name" in partner.json), so letting partners edit it here
	# would rename the document and break every Connect Partner Member row that references
	# it by name. Renaming a partner is an admin-only operation done from the desk.
	"tagline", "description", "country", "city", "address", "website",
	"industry", "year_founded", "rollouts", "hourly_rate", "response_time_hours",
	"sites_deployed", "typical_project_size", "proposal_timeline", "certified_experts",
	"certs_erpnext", "certs_frappe_framework", "countries_served", "references_count",
	"starter_pack", "demo_available", "logo_position_x", "logo_position_y",
)


def update_my_partner_profile(
	partner_name=None, tagline=None, description=None, country=None, city=None,
	address=None, website=None, industry=None, year_founded=None, rollouts=None,
	hourly_rate=None, response_time_hours=None, sites_deployed=None,
	typical_project_size=None, proposal_timeline=None, certified_experts=None,
	certs_erpnext=None, certs_frappe_framework=None, countries_served=None,
	references_count=None, starter_pack=None, demo_available=None,
	logo_position_x=None, logo_position_y=None,
	apps=None, migrations=None, business_processes=None, implementation_types=None, languages=None,
	founder=None, success_stories=None, packs=None, addons=None,
):
	"""Lets any member of the caller's own partner company edit their public profile —
	the same fields (and the same About / Success Stories / Pricing grouping) shown on the
	customer-facing partner profile page."""
	partner = _my_partner()
	doc = frappe.get_doc("Partner", partner)

	values = dict(
		partner_name=partner_name, tagline=tagline, description=description, country=country,
		city=city, address=address, website=website, industry=industry, year_founded=year_founded,
		rollouts=rollouts, hourly_rate=hourly_rate, response_time_hours=response_time_hours,
		sites_deployed=sites_deployed, typical_project_size=typical_project_size,
		proposal_timeline=proposal_timeline, certified_experts=certified_experts,
		certs_erpnext=certs_erpnext, certs_frappe_framework=certs_frappe_framework,
		countries_served=countries_served, references_count=references_count,
		starter_pack=starter_pack, demo_available=demo_available,
		logo_position_x=logo_position_x, logo_position_y=logo_position_y,
	)
	for fieldname in _PROFILE_SIMPLE_FIELDS:
		value = values[fieldname]
		if value is not None:
			doc.set(fieldname, value)

	multiselect_values = dict(
		apps=apps, migrations=migrations, business_processes=business_processes,
		implementation_types=implementation_types, languages=languages,
	)
	for fieldname, child_field in _PROFILE_MULTISELECT_FIELDS.items():
		value = multiselect_values[fieldname]
		if value is not None:
			doc.set(fieldname, [{child_field: v} for v in _parse_json_arg(value, [])])

	founder = _parse_json_arg(founder, None)
	if founder:
		team = doc.get("team") or []
		founder_row = next((row for row in team if row.is_founder), None)
		if not founder_row and founder.get("member_name"):
			founder_row = doc.append("team", {"is_founder": 1})
		if founder_row:
			founder_row.member_name = founder.get("member_name")
			founder_row.designation = founder.get("designation")
			founder_row.bio = founder.get("bio")
			founder_row.photo = founder.get("photo")
			founder_row.photo_position_x = founder.get("photo_position_x", 50)
			founder_row.photo_position_y = founder.get("photo_position_y", 50)

	if success_stories is not None:
		doc.set("success_stories", [
			{
				"client_name": row.get("client_name"),
				"client_logo": row.get("client_logo"),
				"headline": row.get("headline"),
				"category": row.get("category"),
				"url": row.get("url"),
			}
			for row in _parse_json_arg(success_stories, [])
		])

	if packs is not None:
		doc.set("packs", [
			{
				"pack_key": row.get("pack_key"),
				"pack_name": row.get("pack_name"),
				"price": row.get("price"),
				"hours": row.get("hours"),
				"validity_days": row.get("validity_days"),
				"includes_summary": row.get("includes_summary"),
			}
			for row in _parse_json_arg(packs, [])
		])

	if addons is not None:
		doc.set("addons", [
			{"addon_name": row.get("addon_name"), "typical_hours": row.get("typical_hours")}
			for row in _parse_json_arg(addons, [])
		])

	doc.save(ignore_permissions=True)
	return {"partner": doc.name}


def signup_partner(full_name, company_name, email, password, country=None):
	"""Lets a new partner self-signup by creating their user, company, and admin membership in
	one step — same shape as Customer's signup_customer. New partners start unverified (Bronze
	tier, Pending Review) until manually promoted; My Profile is left for them to fill in."""
	full_name = (full_name or "").strip()
	company_name = (company_name or "").strip()
	email = (email or "").strip().lower()
	country = (country or "").strip()
	if not full_name or not company_name or not email or not password:
		frappe.throw(_("Please fill in all fields"))
	if not validate_email_address(email, throw=False):
		frappe.throw(_("Enter a valid email address"))
	if frappe.db.exists("User", email):
		frappe.throw(_("An account with this email already exists. Log in instead."))
	if frappe.db.exists("Partner", company_name):
		frappe.throw(
			_("{0} is already registered. Ask your team admin to add you instead.").format(company_name)
		)

	first_name, _sep, last_name = full_name.partition(" ")

	user = frappe.new_doc("User")
	user.email = email
	user.first_name = first_name
	user.last_name = last_name
	user.user_type = "Website User"
	user.send_welcome_email = 0
	user.new_password = password
	user.insert(ignore_permissions=True)

	partner = frappe.new_doc("Partner")
	partner.partner_name = company_name
	partner.tier = "Bronze"
	partner.country = country
	partner.insert(ignore_permissions=True)

	frappe.get_doc({
		"doctype": "Connect Partner Member",
		"partner": partner.name,
		"user": email,
		"role": "Founder",
		"is_admin": 1,
	}).insert(ignore_permissions=True)

	frappe.local.login_manager.login_as(email)
	return {"ok": True, "partner": partner.name}
