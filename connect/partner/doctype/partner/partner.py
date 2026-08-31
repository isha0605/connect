# Copyright (c) 2026
# For license information, please see license.txt

import json
import difflib
import math
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint, now_datetime

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

PARTNER_FIELDS = [
	"name", "partner_name", "logo", "tagline", "tier", "specialist",
	"rating", "industry", "country", "city", "rollouts", "hourly_rate",
	"response_time_hours",
]
SEARCHABLE_TEXT_FIELDS = ["partner_name", "tagline", "industry", "country", "city"]

# The "is this partner visible at all" gate — combined as AND with whatever
# else a caller filters on. Callers that append more filters must copy this
# (list(BASE_PARTNER_FILTERS)) rather than mutate it in place.
BASE_PARTNER_FILTERS = [["Partner", "is_featured", "=", 1], ["Partner", "enabled", "=", 1]]

SORT_OPTIONS = {
	"rating_desc": ("rating", True),
	"rollouts_desc": ("rollouts", True),
	"name_asc": ("partner_name", False),
}

FILTER_OPERATORS = {"is", "is not", "in", "not in", "=", "!=", "like", "not like", ">", "<", ">=", "<=", "between", "timespan"}

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


class Partner(Document):
	def before_save(self):
		self.region = COUNTRY_TO_REGION.get((self.country or "").strip().lower(), "Other")


def recompute_rating_from_reviews(partner_name, exclude=None):
	"""Recompute a Partner's rating/dimension scores from its (now standalone)
	Partner Review records. Called via doc_events on Partner Review
	insert/update/trash — reviews are no longer a Partner child table, so this
	can't run inside Partner.before_save anymore.

	`exclude`: on_trash fires *before* the row is actually removed from the DB,
	so a plain re-query would still count the row being deleted. Pass the
	doc's own name there to exclude it from the recompute.
	"""
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


def _fts_rank(search_term: str, allowed_names: list[str]):
	"""MariaDB natural-language FULLTEXT search (see the partner_fts index) —
	real relevance ranking, handles multi-word queries well. Returns names in
	relevance order. MySQL's default ft_min_word_len (usually 4) means short
	terms ("erp") won't match here at all; that's what the fuzzy fallback below
	is for."""
	if not allowed_names:
		return []
	rows = frappe.db.sql(
		"""
		SELECT name FROM `tabPartner`
		WHERE name IN %(names)s
		AND MATCH(partner_name, tagline, description, industry, city, country)
			AGAINST (%(term)s IN NATURAL LANGUAGE MODE)
		ORDER BY MATCH(partner_name, tagline, description, industry, city, country)
			AGAINST (%(term)s IN NATURAL LANGUAGE MODE) DESC
		""",
		{"term": search_term, "names": allowed_names},
		as_dict=True,
	)
	return [r.name for r in rows]


def _fuzzy_rank(search_term: str, candidates: list[dict], threshold: float = 0.65):
	"""Typo-tolerant fallback over a bounded candidate set (stdlib difflib, no
	extra dependency — the partner directory is small enough that scoring every
	candidate in Python is cheap). Catches both misspellings ("Tridot" ->
	"Tridots") and terms too short for FULLTEXT's min-word-length ("erp")."""
	term = (search_term or "").strip().lower()
	if not term:
		return candidates

	scored = []
	for c in candidates:
		blob = " ".join(str(c.get(f) or "") for f in SEARCHABLE_TEXT_FIELDS).lower()
		if term in blob:
			score = 1.0
		else:
			whole_ratio = difflib.SequenceMatcher(None, term, blob).ratio()
			word_ratio = max(
				(difflib.SequenceMatcher(None, term, w).ratio() for w in blob.split()), default=0
			)
			score = max(whole_ratio, word_ratio)
		if score >= threshold:
			scored.append((score, c))

	scored.sort(key=lambda pair: pair[0], reverse=True)
	return [c for _, c in scored]


def _partners_matching_child(child_doctype: str, field: str, operator: str, value):
	"""Names of partners with at least one <child_doctype> row satisfying
	<field> <operator> <value> — built as a WHERE name IN (subquery) membership
	check, not a join. Joining the child table directly onto Partner (Frappe's
	own ["Child Doctype", field, op, value] filter syntax does exactly that)
	multiplies a partner's row once per matching child row — combine two or
	more such filters at once (as search_partners' filter panel lets you) and
	a partner with, say, 2 matching rows in one child table and 3 in another
	comes back 6 times instead of once. A membership subquery is a plain
	yes/no test per partner, so it can't fan out no matter how many child rows
	exist on either side."""
	ChildTable = frappe.qb.DocType(child_doctype)
	query = (
		frappe.qb.from_(ChildTable)
		.select(ChildTable.parent)
		.distinct()
		.where(ChildTable.parenttype == "Partner")
	)
	if operator == "=":
		query = query.where(ChildTable[field] == value)
	elif operator == "in":
		query = query.where(ChildTable[field].isin(value))
	elif operator == "is_set":
		query = query.where(ChildTable[field] != "")
	else:
		raise ValueError(f"Unsupported operator: {operator}")
	return {row[0] for row in query.run()}


def _child_values_by_partner(child_doctype: str, value_field: str, names: list[str], parentfield: str | None = None):
	"""Every `value_field` value from `child_doctype` for each partner in
	`names`, in one query, grouped into a dict of lists keyed by partner name
	(full list, in idx order — callers wanting just a preview slice it
	themselves, e.g. apps[:2]). Always scoped to parenttype="Partner"; pass
	`parentfield` too for a child doctype shared with another doctype's own
	Table field (e.g. "Partner App" is also Requirement.apps) so a same-named
	parent from the other doctype can't leak in."""
	if not names:
		return {}
	filters = {"parent": ["in", names], "parenttype": "Partner"}
	if parentfield:
		filters["parentfield"] = parentfield
	values_by_partner = {}
	for r in frappe.get_all(
		child_doctype, filters=filters, fields=["parent", value_field], order_by="idx asc"
	):
		values_by_partner.setdefault(r.parent, []).append(r.get(value_field))
	return values_by_partner


def _apps_by_partner(names: list[str]):
	"""Every Partner App (Partner.apps) value for each partner in `names` —
	see _child_values_by_partner. Kept as its own name since "apps per
	partner" is looked up from several places (search, wizard scoring,
	shortlist), not just the wizard scoring pass."""
	return _child_values_by_partner("Partner App", "app", names, parentfield="apps")


def _parse_answers(answers: dict | str | None):
	"""Normalizes the finder wizard's `answers` payload — arrives as a JSON
	string over the wire (a whitelisted endpoint's raw argument) but as a
	plain dict when one wizard function calls another directly in Python."""
	if isinstance(answers, str):
		answers = json.loads(answers or "{}")
	return answers or {}


def attach_success_story_previews(rows: list[dict]):
	"""Batch-attaches success_story_count/success_story_categories to each row
	in `rows` (each needs a "name" key matching a Partner document) — one
	query regardless of how many rows. Used everywhere a partner listing shows
	this preview: Find Partners search, the finder wizard's results, and the
	customer's Shortlisted page."""
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


def search_partners(
	search: str | None = None,
	industry: str | None = None,
	product: str | None = None,
	region: str | None = None,
	delivery_mode: str | None = None,
	country: str | None = None,
	tier: str | None = None,
	business_process: str | None = None,
	implementation_type: str | None = None,
	language: str | None = None,
	min_rating: float | None = None,
	min_pmm_level: float | None = None,
	max_response_time: int | None = None,
	extra_filters: str | list | None = None,
	sort: str | None = None,
	limit: int = 100,
):
	"""Guest-safe partner search backing the Find Partners page.

	Structured filters combine as AND. `product`/`delivery_mode`/
	`business_process`/`implementation_type`/`language` each resolve to "which
	partners have at least one matching child-table row" via a WHERE name IN
	(subquery) membership check (see _partners_matching_child) rather than
	Frappe's built-in child-table join filter syntax — a join multiplies a
	partner's row once per matching child row, so combining more than one such
	filter at once (this panel lets you) could silently duplicate results. A
	membership subquery can't do that.

	`search` layers full-text search with a fuzzy/typo-tolerant fallback on top
	of whatever the structured filters already narrowed down to:
	1. FULLTEXT relevance search (partner_fts index) — real ranking, good for
	   multi-word queries, but MySQL won't match very short terms.
	2. Fuzzy scoring (Python) over whatever FULLTEXT missed — catches typos and
	   short terms. Only pays its cost on the (small) leftover candidate set.

	`sort`, when given, overrides both the default rating-desc ordering and
	search relevance ranking — an explicit sort choice should win over either.

	`max_response_time` filters on the average-response-time field
	(response_time_hours) — "I want partners who typically respond within X
	hours".

	`extra_filters` is a JSON list of [fieldname, operator, value] triples from
	the CRM-style Filter component (frappe-ui's meta-driven field/operator/value
	picker) — validated against Partner's own meta before being appended, so a
	malformed/garbage fieldname or operator is dropped rather than passed through.
	"""
	filters = list(BASE_PARTNER_FILTERS)
	if industry:
		filters.append(["Partner", "industry", "=", industry])
	if region:
		filters.append(["Partner", "region", "=", region])
	if country:
		filters.append(["Partner", "country", "=", country])
	if tier:
		filters.append(["Partner", "tier", "=", tier])

	child_matches = []
	if product:
		child_matches.append(_partners_matching_child("Partner App", "app", "=", product))
	if delivery_mode:
		child_matches.append(_partners_matching_child("Partner Delivery Mode", "delivery_mode", "=", delivery_mode))
	if business_process:
		child_matches.append(_partners_matching_child("Partner Business Process", "business_process", "=", business_process))
	if implementation_type:
		child_matches.append(_partners_matching_child("Partner Implementation Type", "implementation_type", "=", implementation_type))
	if language:
		child_matches.append(_partners_matching_child("Partner Language", "language", "=", language))
	if child_matches:
		filters.append(["Partner", "name", "in", list(set.intersection(*child_matches))])

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
		candidates = frappe.get_list("Partner", fields=PARTNER_FIELDS, filters=filters, limit_page_length=0)
		by_name = {c.name: c for c in candidates}

		ranked_names = _fts_rank(search, list(by_name))
		ordered = [by_name[n] for n in ranked_names]

		leftover = [c for c in candidates if c.name not in set(ranked_names)]
		ordered += _fuzzy_rank(search, leftover)

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


def count_matching_partners(answers: dict | str | None = None):
	"""Live "partners that match so far" count for the finder wizard's dot-grid,
	recomputed cumulatively after every answer. Filters combine as AND, narrowing
	as more (mappable) answers come in — only questions with a real mapping to
	Partner data affect the count."""
	answers = _parse_answers(answers)
	filters = list(BASE_PARTNER_FILTERS)
	child_matches = []

	industry = answers.get("industry")
	if industry:
		filters.append(["Partner", "industry", "=", WIZARD_TO_PARTNER_INDUSTRY.get(industry, industry)])

	impl_type = LOOKING_FOR_TO_IMPL_TYPE.get(answers.get("looking_for"))
	if impl_type:
		child_matches.append(_partners_matching_child("Partner Implementation Type", "implementation_type", "=", impl_type))

	situation = answers.get("current_situation")
	migration = CURRENT_SITUATION_TO_MIGRATION.get(situation)
	if migration:
		child_matches.append(_partners_matching_child("Partner Migration Path", "migration_path", "=", migration))
	else:
		impl_type_2 = CURRENT_SITUATION_TO_IMPL_TYPE.get(situation)
		if impl_type_2:
			child_matches.append(_partners_matching_child("Partner Implementation Type", "implementation_type", "=", impl_type_2))

	mode = DELIVERY_TO_MODE.get(answers.get("delivery_preference"))
	if mode:
		child_matches.append(_partners_matching_child("Partner Delivery Mode", "delivery_mode", "=", mode))

	requirements = answers.get("requirements") or []
	bp_values = [REQUIREMENT_TO_BUSINESS_PROCESS[r] for r in requirements if r in REQUIREMENT_TO_BUSINESS_PROCESS]
	if bp_values:
		child_matches.append(_partners_matching_child("Partner Business Process", "business_process", "in", bp_values))
	elif any(r in REQUIREMENT_MIGRATION_TAGS for r in requirements):
		child_matches.append(_partners_matching_child("Partner Migration Path", "migration_path", "is_set", None))

	if child_matches:
		filters.append(["Partner", "name", "in", list(set.intersection(*child_matches))])

	partners = frappe.get_list("Partner", filters=filters, fields=["name"], limit_page_length=0)
	return len(partners)


def _score_partners_by_requirements(answers: dict):
	"""Shared scoring for the finder wizard: every is_featured partner scored by
	how many of the wizard's answered questions they fail to satisfy. Returns the
	full, unfiltered [(missing_count, -rating, name, missing_labels)] list sorted
	best-first — callers decide their own cutoff."""
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


def wizard_match_state(answers: dict | str | None = None):
	"""Live per-partner matched state for the finder wizard's dot pictogram —
	counts exact matches only (missing_count == 0), the same thing the results
	page's own "N Partners Match Your Requirements" header counts, so the two
	numbers always agree without needing a separate threshold to keep in sync."""
	answers = _parse_answers(answers)

	all_scored, _apps_by_partner, _answered_dims = _score_partners_by_requirements(answers)
	exact = [s for s in all_scored if s[0] == 0]
	matched_names = [name for *_rest, name, _missing in exact]
	return {"matched_names": matched_names, "count": len(matched_names)}


def list_matching_partners(answers: dict | str | None = None, limit: int = 8):
	"""Ranked partner results for the finder wizard's final step. Same scoring
	as wizard_match_state (see _score_partners_by_requirements), returning full
	rows (same shape as search_partners) instead of just names."""
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


def list_partner_countries():
	"""Distinct countries with at least one Partner, for the Country filter dropdown."""
	rows = frappe.get_all(
		"Partner", fields=["country"], filters={"country": ["is", "set"], "is_featured": 1, "enabled": 1}, distinct=True
	)
	return sorted({row.country for row in rows if row.country})


def list_partner_filter_options():
	"""Option lists for the Find Partners filter panel's Business Process /
	Implementation Type / Language dropdowns, plus the finder wizard's Apps
	question."""
	return {
		"business_processes": frappe.get_all("Business Process", pluck="title", order_by="title"),
		"implementation_types": frappe.get_all("Implementation Type", pluck="title", order_by="title"),
		"languages": frappe.get_all("FC Language", pluck="title", order_by="title"),
		"apps": frappe.get_all("App", pluck="title", order_by="title"),
	}


def _pack_is_primary_match(pack_key: str, has_erpnext: bool, has_hr: bool):
	if pack_key == "allinone":
		return has_erpnext and has_hr
	if pack_key in ("core", "manufacturing"):
		return has_erpnext and not has_hr
	if pack_key == "hr":
		return has_hr and not has_erpnext
	return False


def get_partner_preview(partner: str):
	"""Lightweight partner snapshot for the Find Partners list view's quick-preview
	side drawer — just enough to decide whether to open the full profile."""
	fields = [
		"name", "partner_name", "logo", "description", "tier", "specialist",
		"rating", "city", "country", "pmm_level", "hourly_rate",
		"certs_erpnext", "certs_frappe_framework", "industry", "address",
	]
	doc = frappe.db.get_value("Partner", partner, fields, as_dict=True)
	if not doc:
		frappe.throw(_("Partner not found"), frappe.DoesNotExistError)

	doc["apps"] = frappe.get_all(
		"Partner App",
		filters={"parent": partner, "parenttype": "Partner", "parentfield": "apps"},
		pluck="app",
		order_by="idx asc",
	)
	doc["migrations"] = frappe.get_all(
		"Partner Migration Path", filters={"parent": partner}, pluck="migration_path", order_by="idx asc"
	)
	return doc


def get_partner_document(partner: str):
	"""Full Partner record for the Partner Profile page."""
	if not frappe.db.exists("Partner", partner):
		frappe.throw(_("Partner not found"), frappe.DoesNotExistError)
	doc = frappe.get_doc("Partner", partner).as_dict()
	# computed, not stored — "founded_years_ago" would silently go stale every
	# year if we persisted it instead of deriving it from year_founded on read
	doc["founded_years_ago"] = (
		now_datetime().year - doc["year_founded"] if doc.get("year_founded") else None
	)
	return doc

