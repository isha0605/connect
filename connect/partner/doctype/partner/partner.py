# Copyright (c) 2026
# For license information, please see license.txt

import json
import math
from collections import Counter

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Max
from frappe.utils import cint, flt, now_datetime
from frappe.utils.data import cast

from connect.partner.industries import (
	attach_industries,
	industries_by_partner,
	industry_badges,
	partners_in_industries,
	picked_industries,
	suggested_industries,
	validate_industries,
)
from connect.partner.logo import attach_normalized_logos
from connect.partner.story_image import queue_missing_story_images
from connect.partner.doctype.connect_partner_member.connect_partner_member import get_current_membership
from connect.partner.doctype.region.region import get_filter_countries, get_region_of_country
from connect.permissions import _has_full_access, _is_partner_admin

DIMENSION_SCORE_FIELDS = (
	"business_understanding",
	"implementation_quality",
	"communication",
	"timeliness",
	"support",
	"technical_expertise",
)


class Partner(Document):
	def autoname(self):
		"""A partner who signs up in Connect is named by their display name. Partners from frappe.io
		keep their frappe.io ID instead, so they may share a display name (see save_imported_partner)."""
		name = (self.partner_name or "").strip()
		if not name:
			frappe.throw(_("Partner Name is required."), frappe.MandatoryError)
		if frappe.db.exists("Partner", name):
			frappe.throw(_("A partner named {0} already exists.").format(frappe.bold(name)), frappe.DuplicateEntryError)
		self.name = name

	def validate(self):
		self.validate_hourly_rate()
		self.validate_served_countries()
		validate_industries(self)
		self.set_starter_pack_sequence()

	def validate_hourly_rate(self):
		if flt(self.hourly_rate) < 0:
			frappe.throw(_("Hourly rate can't be negative."))

	def set_starter_pack_sequence(self):
		"""Gives each Starter Pack partner a unique rotation slot so paid orders round-robin fairly."""
		if not self.starter_pack:
			self.starter_pack_sequence = 0
			return

		if cint(self.starter_pack_sequence) <= 0:
			Partner = frappe.qb.DocType("Partner")
			last = (
				frappe.qb.from_(Partner)
				.select(Max(Partner.starter_pack_sequence))
				.where((Partner.starter_pack == 1) & (Partner.name != self.name))
			).run()[0][0]
			self.starter_pack_sequence = cint(last) + 1
			return

		taken_by = frappe.db.get_value(
			"Partner",
			{"starter_pack": 1, "starter_pack_sequence": self.starter_pack_sequence, "name": ["!=", self.name]},
			"partner_name",
		)
		if taken_by:
			frappe.throw(
				_("Starter Pack Rotation Order {0} is already {1}'s. Each partner needs their own.").format(
					self.starter_pack_sequence, frappe.bold(taken_by)
				)
			)

	def validate_country(self):
		if self.country and not frappe.db.exists("Country", self.country):
			frappe.throw(_("{0} is not in the Country list.").format(self.country))

	def validate_served_countries(self):
		counts = Counter(row.country for row in self.served_countries)
		repeated = {country for country, count in counts.items() if count > 1}
		if repeated:
			frappe.throw(_("{0} is listed more than once in Countries Served.").format(", ".join(sorted(repeated))))

	def before_save(self):
		self.region = get_region_of_country(self.country)
		self.countries_served = len(self.served_countries)

	def on_update(self):
		# background-fetches each success story's own frappe.io cover photo —
		# never blocks this save, and no-ops for rows that already have one
		queue_missing_story_images(self.get("success_stories"))


def save_imported_partner(frappe_io_id: str, values: dict) -> str:
	"""Creates or updates the partner whose ID is its frappe.io ID, and returns that ID. The ID
	never changes, so running the import again updates partners instead of duplicating them."""
	# The import is a system job, not a user, so it writes without the caller's permissions.
	if frappe.db.exists("Partner", frappe_io_id):
		doc = frappe.get_doc("Partner", frappe_io_id)
		doc.update(values)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "Partner", **values})
		doc.insert(ignore_permissions=True, set_name=frappe_io_id)
	return doc.name


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


def _normalize_multi(value):
	"""A filter value arriving from the directory's multi-select facets is a JSON-array string
	over the wire; a single string (from an older/simpler caller) stays a plain scalar so existing
	single-value callers keep working unchanged."""
	if value in (None, ""):
		return None
	if isinstance(value, (list, tuple)):
		return list(value)
	if isinstance(value, str) and value.strip().startswith("["):
		try:
			parsed = json.loads(value)
			if isinstance(parsed, list):
				return parsed
		except ValueError:
			pass
	return value


PARTNER_FIELDS = [
	"name", "partner_name", "logo", "logo_icon", "tagline", "tier", "specialist",
	"rating", "country", "city", "rollouts", "hourly_rate",
	"response_time_hours",
]
# The "is this partner visible at all" gate — combined as AND with whatever
# else a caller filters on. Callers that append more filters must copy this
# (list(BASE_PARTNER_FILTERS)) rather than mutate it in place.
# Only a partner Frappe has approved (their Partner Application) is listed and can be sent work.
# Guests have no read on Partner, so the directory reads with frappe.get_all and these filters
# decide what is public.
VERIFIED = "Verified"
BASE_PARTNER_FILTERS = [
	["Partner", "show_in_website", "=", 1],
	["Partner", "enabled", "=", 1],
	["Partner", "verification_status", "=", VERIFIED],
]
# Workflow state the public profile never shows: unpublished edits and Frappe-side flags.
PRIVATE_PROFILE_FIELDS = (
	"profile_draft", "cloud_registration", "cloud_registration_sent_on", "show_in_website", "starter_pack_sequence",
)


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


def _business_processes_by_partner(names):
	"""Every Partner Business Process (Partner.business_processes) value for each partner in
	`names` — see _child_values_by_partner. Used as the directory card's "Expertise across ..."
	fallback line for partners with no success stories yet."""
	return _child_values_by_partner(
		"Partner Business Process", "business_process", names, parentfield="business_processes"
	)


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
	already narrowed it in SQL before this ever runs — see search_partners.

	Returns None (not []) when the search index itself is unavailable, so a caller can tell "the
	index is down, fall back to showing everyone" apart from "the index ran and genuinely found no
	match" — collapsing those into the same [] previously made every search silently return the
	full unfiltered list regardless of the query, since a real zero-match query looked identical to
	an unavailable index."""
	if not allowed_names:
		return []
	from connect.search import PartnerSearch

	search = PartnerSearch()
	if not (search.is_search_enabled() and search.index_exists()):
		return None
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
	category=None, exclude=None, served_country=None,
	min_rating=None, min_pmm_level=None, max_response_time=None,
	extra_filters=None,
	sort=None, limit=100,
):
	"""Searches partners for the Find Partners page, combining structured filters with full-text and fuzzy search."""
	industry = _normalize_multi(industry)
	country = _normalize_multi(country)
	category = _normalize_multi(category)
	product = _normalize_multi(product)
	served_country = _normalize_multi(served_country)

	filters = list(BASE_PARTNER_FILTERS)
	for value, field in [
		(region, "region"), (country, "country"), (tier, "tier"),
	]:
		if value:
			filters.append(["Partner", field, "in" if isinstance(value, list) else "=", value])

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
		(served_country, "Partner Served Country", "country", "served_countries"),
	]:
		if value:
			op = "in" if isinstance(value, list) else "="
			child_matches.append(_partners_matching_child(doctype, field, op, value, parentfield=parentfield))
	if industry:
		child_matches.append(partners_in_industries(industry if isinstance(industry, list) else [industry]))
	if child_matches:
		filters.append(["Partner", "name", "in", list(set.intersection(*child_matches)) or [""]])

	exclude = _normalize_multi(exclude)
	if exclude:
		filters.append(["Partner", "name", "not in", exclude if isinstance(exclude, list) else [exclude]])

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
		partners = frappe.get_all(
			"Partner", fields=PARTNER_FIELDS, filters=filters, order_by=order_by, limit_page_length=limit
		)
	else:
		# Candidates passing the structured filters — unranked, no text match yet.
		candidates = frappe.get_all("Partner", fields=PARTNER_FIELDS, filters=filters)
		by_name = {c.name: c for c in candidates}

		ranked_names = _sqlite_rank(search, list(by_name))
		if ranked_names is None:
			# Search index unavailable — fall back to the structured-filtered candidates
			# unranked rather than showing nobody.
			partners = candidates[:limit]
		else:
			ranked = [by_name[n] for n in ranked_names]
			# Frappe's FTS5 layer only prefix-wildcards terms of 4+ chars (MIN_WORD_LENGTH in
			# sqlite_search.py) — a still-being-typed query like "aur" is searched as an exact
			# 3-letter word, which "Auriga IT" can never satisfy. Patch that gap (and any other
			# tokenizer miss, e.g. a mid-word fragment) with a plain substring match over the
			# same structured-filtered candidates, appended after the ranked results.
			ranked_set = set(ranked_names)
			term = search.lower()
			substring_matches = [
				c for c in candidates
				if c.name not in ranked_set and term in (c.partner_name or "").lower()
			]
			partners = (ranked + substring_matches)[:limit]
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

	attach_industries(partners)
	attach_success_story_previews(partners)
	return partners


# The finder wizard's industry answers are broader than the Industry list partners pick from —
# translate each to the closest Industry; matching then also takes in that Industry's group.
WIZARD_TO_PARTNER_INDUSTRY = {
	"Manufacturing": "Manufacturing",
	"Retail & Distribution": "Trading and Distribution",
	"Healthcare": "Healthcare",
	"Education": "Education",
	"Services": "Services",
	"Construction": "Engineering and Construction",
	"Logistics": "Logistics",
	"Technology": "Technology",
	"Other": "Others",
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
	# Same listing scope as search_partners, so the wizard's live count never
	# exceeds what the directory shows.
	filters = list(BASE_PARTNER_FILTERS)

	# Same membership-subquery approach as search_partners — see _partners_matching_child.
	child_matches = []

	industry = answers.get("industry")
	if industry:
		child_matches.append(partners_in_industries([WIZARD_TO_PARTNER_INDUSTRY.get(industry, industry)]))

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

	partners = frappe.get_all("Partner", filters=filters, fields=["name"])
	return len(partners)


def _score_partners_by_requirements(answers):
	"""Scores every directory-listed partner by how many of the wizard's answered questions they fail to match, shared by wizard_match_state and list_matching_partners."""
	names = [n.name for n in frappe.get_all(
		"Partner", filters=BASE_PARTNER_FILTERS, fields=["name"], limit_page_length=0,
	)]
	if not names:
		return [], {}

	rows = frappe.get_all("Partner", filters=[["Partner", "name", "in", names]], fields=PARTNER_FIELDS)
	by_name = {r.name: r for r in rows}

	apps_by_partner = _apps_by_partner(names)
	delivery_by = _child_values_by_partner("Partner Delivery Mode", "delivery_mode", names)
	migrations_by = _child_values_by_partner("Partner Migration Path", "migration_path", names)
	impl_by = _child_values_by_partner("Partner Implementation Type", "implementation_type", names)
	bp_by = _child_values_by_partner("Partner Business Process", "business_process", names)

	industry = answers.get("industry")
	wanted_industry = WIZARD_TO_PARTNER_INDUSTRY.get(industry, industry) if industry else None
	in_wanted_industry = partners_in_industries([wanted_industry]) if wanted_industry else set()

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
	# listed pool look like a "near match" when only 2-3 were, which is exactly
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
		if wanted_industry and name not in in_wanted_industry:
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
	rows = frappe.get_all("Partner", filters=[["Partner", "name", "in", names]], fields=PARTNER_FIELDS)
	by_name = {r.name: r for r in rows}

	scored = scored[:limit]

	result = []
	for _missing_count, _neg_rating, name, missing in scored:
		row = dict(by_name[name])
		row["apps_preview"] = apps_by_partner.get(name, [])[:2]
		row["missing_label"] = ", ".join(missing) if missing else None
		result.append(row)

	attach_industries(result)
	attach_success_story_previews(result)
	return result


# The region map's shapes, keyed by Region. India has its own shape, apart from Asia Pacific.
MAP_REGION_KEYS = {
	"India": "india",
	"Asia Pacific": "asia",
	"Middle East": "middle_east",
	"Africa": "africa",
	"Europe": "europe",
	"Americas": "americas",
}


def region_presence_counts():
	"""Partner counts for the Find Partners region map. Counts every enabled, Verified partner,
	not only the ones listed in the directory, since the map shows presence, not profiles."""
	rows = frappe.get_all(
		"Partner", fields=["country", "region"], filters={"enabled": 1, "verification_status": VERIFIED}
	)
	counts = Counter("India" if row.country == "India" else row.region for row in rows)
	return {key: counts.get(region, 0) for region, key in MAP_REGION_KEYS.items()}


def _decorate_directory_rows(rows):
	"""Adds the review_count/success-story preview fields the directory card list needs on top of
	whatever search_partners already returned. Shared by list_directory_partners and the wizard
	hand-off (list_directory_partners_for_wizard) so both render identical cards."""
	names = [r.name for r in rows]
	review_partners = frappe.get_all("Partner Review", filters={"partner": ["in", names]}, pluck="partner") if names else []
	review_counts = Counter(review_partners)
	for row in rows:
		row["review_count"] = review_counts.get(row.name, 0)

	# rows from search_partners have them already; the Shortlist's own query doesn't
	attach_industries([row for row in rows if "industries" not in row])
	attach_success_story_previews(rows)

	business_processes = _business_processes_by_partner(names)
	for row in rows:
		row["business_processes"] = business_processes.get(row.name, [])
	return rows


def list_partners_by_names(names):
	"""Full directory-card rows for an explicit list of partner names, decorated the same way as
	list_directory_partners. Used by the Shortlisted page to render partners a guest has bookmarked
	locally (localStorage) before logging in, since no server-side Shortlist row exists for them yet."""
	names = _normalize_multi(names)
	if not names:
		return []
	filters = list(BASE_PARTNER_FILTERS) + [["Partner", "name", "in", names]]
	rows = frappe.get_all("Partner", fields=PARTNER_FIELDS, filters=filters)
	apps_by_partner = _apps_by_partner([r.name for r in rows])
	for r in rows:
		r["apps_preview"] = apps_by_partner.get(r.name, [])[:2]
	return _decorate_directory_rows(rows)


def list_directory_partners(
	limit=9, search=None, tier=None, country=None, industry=None, category=None, product=None,
	business_process=None, implementation_type=None, language=None,
	min_rating=None, max_response_time=None, exclude=None,
):
	"""Returns directory-listed partners (name, logo, tier, rating, rate, response time, success stories)
	for the Partner Directory redesign's card list and its filter row. Filtering/search/ordering is
	delegated to search_partners — the same engine behind the Find Partners page — so both stay
	consistent; this only adds the review_count/success-story preview fields the card list needs on
	top, same as before this had its own filters. `country`/`category`/`product` accept either a
	single value or a JSON array (the Region/Industry/App filters' multi-select). `exclude` (name
	not-in) is what the "Proven in other industries" section uses to call this same function a
	second time with category dropped, without repeating whoever's already shown in the main list."""
	rows = search_partners(
		search=search, tier=tier, country=country, industry=industry, category=category, product=product,
		business_process=business_process, implementation_type=implementation_type, language=language,
		min_rating=min_rating, max_response_time=max_response_time, exclude=exclude,
		limit=cint(limit) or 9,
	)
	return _decorate_directory_rows(rows)


def list_country_facets(search=None, tier=None, industry=None, category=None,
	business_process=None, implementation_type=None, language=None,
	min_rating=None, max_response_time=None):
	"""Country counts for the Directory's Region>Country multi-select, computed with every OTHER
	active filter applied but NOT country itself — so checking a country never shrinks its own
	sibling counts, only what the other facets (industry, tier, ...) show. Lists the countries each
	Region marks Show in Directory Filter, even at 0, not just ones a partner happens to be in today."""
	rows = search_partners(
		search=search, tier=tier, industry=industry, category=category,
		business_process=business_process, implementation_type=implementation_type, language=language,
		min_rating=min_rating, max_response_time=max_response_time, limit=10000,
	)
	counts = Counter(r.country for r in rows)
	return [
		{"region": region, "options": [{"value": c, "count": counts.get(c, 0)} for c in countries]}
		for region, countries in get_filter_countries().items()
	]


def list_industry_facets(search=None, tier=None, country=None,
	business_process=None, implementation_type=None, language=None,
	min_rating=None, max_response_time=None):
	"""Industry>Segment counts for the Directory's Industry multi-select, computed with every OTHER
	active filter applied but not industry/category themselves. Groups are the industries partners
	picked (a partner counts under each of theirs); each group's children are whichever success-story
	categories actually occur among that group's partners."""
	rows = search_partners(
		search=search, tier=tier, country=country,
		business_process=business_process, implementation_type=implementation_type, language=language,
		min_rating=min_rating, max_response_time=max_response_time, limit=10000,
	)
	names = [r.name for r in rows]
	industry_counts = Counter(industry for r in rows for industry in r.industries)

	categories_by_partner = {}
	if names:
		for row in frappe.get_all(
			"Partner Success Story", filters={"parent": ["in", names]}, fields=["parent", "category"]
		):
			if row.category:
				categories_by_partner.setdefault(row.parent, set()).add(row.category)

	facets = []
	for industry, group_count in industry_counts.most_common():
		group_names = [r.name for r in rows if industry in r.industries]
		category_counts = Counter()
		for pname in group_names:
			for cat in categories_by_partner.get(pname, ()):
				category_counts[cat] += 1
		facets.append({
			"industry": industry,
			"count": group_count,
			"options": [
				{"value": cat, "count": n} for cat, n in sorted(category_counts.items(), key=lambda kv: -kv[1])
			],
		})
	return facets


def list_directory_filter_facets(search=None, tier=None, industry=None, country=None, category=None,
	business_process=None, implementation_type=None, language=None,
	min_rating=None, max_response_time=None):
	"""Both facet panels in one call, so the Directory's filter row only needs one resource."""
	return {
		"regions": list_country_facets(
			search=search, tier=tier, industry=industry, category=category,
			business_process=business_process, implementation_type=implementation_type, language=language,
			min_rating=min_rating, max_response_time=max_response_time,
		),
		"industries": list_industry_facets(
			search=search, tier=tier, country=country,
			business_process=business_process, implementation_type=implementation_type, language=language,
			min_rating=min_rating, max_response_time=max_response_time,
		),
	}


def list_partner_tiers():
	"""Returns the tiers actually in use among directory-listed partners (same show_in_website/enabled
	scope as list_directory_partners), highest first as the Tier field lists them, for the Tier filter dropdown."""
	rows = frappe.get_all("Partner", fields=["tier"], filters=BASE_PARTNER_FILTERS, distinct=True)
	present = {row.tier for row in rows if row.tier}
	return [tier for tier in tier_order() if tier in present]


def tier_order() -> list[str]:
	"""Partner tiers, highest first, as the Tier field lists them."""
	return [tier for tier in frappe.get_meta("Partner").get_options("tier").split("\n") if tier]


def list_partner_countries():
	"""Returns distinct countries of directory-listed partners, for the Country filter dropdown."""
	filters = [*BASE_PARTNER_FILTERS, ["Partner", "country", "is", "set"]]
	rows = frappe.get_all("Partner", fields=["country"], filters=filters, distinct=True)
	return sorted({row.country for row in rows if row.country})


def list_partner_industries():
	"""Returns distinct industries actually picked among directory-listed partners (same
	show_in_website/enabled scope as list_directory_partners), for the Industry filter dropdown —
	deliberately not the full Industry list, so a value with zero partners behind it doesn't show
	up as a dead-end filter."""
	listed = frappe.get_all("Partner", filters=BASE_PARTNER_FILTERS, pluck="name")
	return sorted({industry for industries in industries_by_partner(listed).values() for industry in industries})


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
		"rating", "city", "country", "pmm_level", "hourly_rate", "response_time_hours",
		"certs_erpnext", "certs_frappe_framework", "address",
	]
	check_profile_visible(partner)
	doc = frappe.db.get_value("Partner", partner, fields, as_dict=True)

	doc["apps"] = _apps_by_partner([partner]).get(partner, [])
	attach_industries([doc])
	doc["migrations"] = frappe.get_all(
		"Partner Migration Path", filters={"parent": partner}, pluck="migration_path", order_by="idx asc"
	)
	return doc


def get_partner_document(partner):
	"""Returns the full Partner record as a plain API call, since Studio's Document resource isn't guest-accessible."""
	check_profile_visible(partner)
	doc = frappe.get_doc("Partner", partner).as_dict()
	for fieldname in PRIVATE_PROFILE_FIELDS:
		doc.pop(fieldname, None)
	# computed, not stored — "founded_years_ago" would silently go stale every
	# year if we persisted it instead of deriving it from year_founded on read
	doc["founded_years_ago"] = (
		now_datetime().year - doc["year_founded"] if doc.get("year_founded") else None
	)
	industries = [row.industry for row in doc.get("industries") or []]
	# the picked industries, each with the verified tick its success stories earn
	doc["industry_badges"] = industry_badges(industries, doc.get("success_stories"))
	doc["display_industries"] = industries
	# adds client_logo_display per success story — a greyscale-normalized copy of
	# the client logo where one has been built, else the original URL
	attach_normalized_logos(doc.get("success_stories"))
	return doc


def check_profile_visible(partner: str) -> None:
	"""A listed partner's profile is public. An unlisted one opens only for its own members
	(to preview it) and Frappe staff; for anyone else it does not exist."""
	is_listed = frappe.db.exists("Partner", {"name": partner, "enabled": 1, "verification_status": VERIFIED})
	if is_listed or _can_see_unlisted_partner(partner):
		return
	frappe.throw(_("Partner not found"), frappe.DoesNotExistError)


def _can_see_unlisted_partner(partner: str) -> bool:
	user = frappe.session.user
	if _has_full_access(user) or "Partner Reviewer" in frappe.get_roles(user):
		return True
	return bool(frappe.db.exists("Connect Partner Member", {"partner": partner, "user": user, "is_removed": 0}))


def _my_partner():
	"""Resolves the partner the caller works for now, throwing if they aren't on a partner's roster.
	Read from their partner membership alone, as the sidebar does: someone who is also on a
	customer's team still works for their partner."""
	membership = get_current_membership(frappe.session.user)
	if not membership:
		frappe.throw(_("You are not a member of any partner company"), frappe.PermissionError)
	return membership.partner


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
	"industries": "industry",
	"delivery_options": "delivery_mode",
}

# cover_image too: a story without a frappe.io cover keeps the one it was given
_STORY_FIELDS = ("client_name", "client_logo", "headline", "category", "url", "cover_image")
_FOUNDER_FIELDS = ("member_name", "designation", "bio", "photo")
# Profile tables saved whole, with the fields each row keeps.
_PROFILE_ROW_FIELDS = {
	"success_stories": _STORY_FIELDS,
	"photos": ("image", "video"),
	"addons": ("addon_name", "typical_hours"),
}

_PROFILE_SIMPLE_FIELDS = (
	# partner_name is deliberately excluded: the name customers see is set by Frappe, from the
	# partner's application or frappe.io, not by the partner.
	# starter_pack is excluded too: it decides who Frappe may assign paid Starter Pack
	# orders to, so a partner must not be able to enrol themselves. So are certs_erpnext and
	# certs_frappe_framework: they're counted from linked certificates (recount_certificates),
	# and countries_served, counted from served_countries. rollouts, sites_deployed, certified_experts
	# and references_count come from frappe.io's import, so partners can't overwrite them.
	"tagline", "description", "country", "city", "address", "website",
	"year_founded", "hourly_rate", "typical_project_size", "proposal_timeline",
	"demo_available", "logo_position_x", "logo_position_y", "phone", "team_size", "journey_blog_url",
	"logo", "logo_icon", "why_choose_them", "how_we_work", "successful_implementation", "origin_story",
)

# What the partner's Profile builder edits, beyond the lists below.
_BUILDER_FIELDS = (
	"tagline", "website", "phone", "journey_blog_url", "logo", "logo_icon", "description", "year_founded",
	"team_size", "certs_erpnext", "certs_frappe_framework", "address", "city", "country",
	"hourly_rate", "why_choose_them", "how_we_work", "successful_implementation", "origin_story",
)
# Longest text each profile field may hold, so every partner's profile lays out the same way.
# The Profile builder shows the same limits as it counts.
_TEXT_LIMITS = {
	"tagline": 80, "address": 200, "description": 500, "why_choose_them": 300, "how_we_work": 300,
	"successful_implementation": 300, "origin_story": 400,
}
_FOUNDER_LIMITS = {"member_name": 60, "designation": 40, "bio": 280}
_STORY_LIMITS = {"client_name": 40, "headline": 90}

# Shown on the public profile, so a link must be an upload, an app asset or an https page.
_MEDIA_PREFIXES = ("/files/", "/assets/", "https://")
# Most photos and videos a gallery holds. A video row also has an image: its poster.
_MAX_GALLERY_PHOTOS = 6
_MAX_GALLERY_VIDEOS = 2


def get_my_profile(with_draft=False) -> dict:
	"""Everything the caller's Profile builder and Listing show: their own partner's public profile,
	what Frappe sets for them (tier, PMM, verification), and whether they may edit it (admin only).
	With `with_draft`, the profile shows the admin's unpublished changes."""
	partner = _my_partner()
	doc = frappe.get_doc("Partner", partner)
	draft = _profile_draft(doc)
	if cint(with_draft):
		_apply_profile_values(doc, draft)

	founder = next((row for row in doc.team if row.is_founder), None)
	stories = [{field: row.get(field) for field in _STORY_FIELDS} for row in doc.success_stories]
	attach_normalized_logos(stories)
	return {
		"partner": doc.name,
		"partner_name": doc.partner_name,
		**{fieldname: doc.get(fieldname) for fieldname in _BUILDER_FIELDS},
		"apps": [row.app for row in doc.apps],
		"migrations": [row.migration_path for row in doc.migrations],
		"served_countries": [row.country for row in doc.served_countries],
		"delivery_options": [row.delivery_mode for row in doc.delivery_options],
		"founder": {field: founder.get(field) for field in _FOUNDER_FIELDS} if founder else {},
		"photos": [{"image": row.image, "video": row.video} for row in doc.photos],
		"success_stories": stories,
		"industries": picked_industries(doc),
		# the picked industries as the public profile shows them, with their verified tick
		"industry_badges": industry_badges(picked_industries(doc), stories),
		"suggested_industries": suggested_industries(picked_industries(doc), stories),
		"tier": doc.tier,
		"pmm_level": doc.pmm_level,
		"is_verified": doc.verification_status == "Verified",
		"can_edit": _is_partner_admin(partner, frappe.session.user),
		"has_unpublished_changes": bool(draft),
		"options": _profile_options(),
	}


def _profile_options() -> dict:
	return {
		"apps": frappe.get_all("App", pluck="name", order_by="name asc"),
		"countries": frappe.get_all("Country", pluck="name", order_by="name asc"),
		"migrations": frappe.get_all("Migration Path", pluck="name", order_by="name asc"),
		"industries": frappe.get_all("Industry", pluck="name", order_by="name asc"),
		"delivery_modes": frappe.get_all("Delivery Mode", pluck="name", order_by="name asc"),
		"categories": sorted(set(frappe.get_all("Partner Success Story", filters={"category": ["is", "set"]}, pluck="category"))),
	}


def _limited_texts(doc) -> list[tuple]:
	"""(where, row, fieldname, limit) for every profile text that has a length limit."""
	rows = [("partner", doc, _TEXT_LIMITS)]
	rows += [("founder", row, _FOUNDER_LIMITS) for row in doc.team if row.is_founder]
	rows += [("story", row, _STORY_LIMITS) for row in doc.success_stories]
	return [(where, row, fieldname, limit) for where, row, limits in rows for fieldname, limit in limits.items()]


def _check_profile_lengths(doc, before) -> None:
	"""Refuses text over its limit, but only text this save changes: text saved before the limits
	existed doesn't stop a partner saving the rest of their profile."""
	unchanged = {(where, fieldname, row.get(fieldname) or "") for where, row, fieldname, _limit in _limited_texts(before)}
	for where, row, fieldname, limit in _limited_texts(doc):
		value = row.get(fieldname) or ""
		if len(value) > limit and (where, fieldname, value) not in unchanged:
			label = _(row.meta.get_label(fieldname))
			frappe.throw(_("{0} is {1} characters long; the limit is {2}.").format(label, len(value), limit))


def _check_profile_media(doc) -> None:
	links = [doc.logo, doc.logo_icon]
	links += [row.photo for row in doc.team]
	links += [link for row in doc.photos for link in (row.image, row.video)]
	links += [link for row in doc.success_stories for link in (row.client_logo, row.cover_image)]
	for link in filter(None, links):
		if not link.startswith(_MEDIA_PREFIXES):
			frappe.throw(_("Images and videos must be uploaded files or https links: {0}").format(link))


def _check_gallery_size(doc, live) -> None:
	"""A gallery the partner changed must keep to the limits; one saved before them still saves."""
	rows = [(row.image or "", row.video or "") for row in doc.photos]
	if rows == [(row.image or "", row.video or "") for row in live.photos]:
		return

	videos = sum(1 for _image, video in rows if video)
	if videos > _MAX_GALLERY_VIDEOS:
		frappe.throw(_("Add up to {0} videos.").format(_MAX_GALLERY_VIDEOS))
	if len(rows) - videos > _MAX_GALLERY_PHOTOS:
		frappe.throw(_("Add up to {0} photos.").format(_MAX_GALLERY_PHOTOS))


def update_my_partner_profile(
	tagline=None, description=None, country=None, city=None,
	address=None, website=None, year_founded=None,
	hourly_rate=None,
	typical_project_size=None, proposal_timeline=None,
	demo_available=None,
	logo_position_x=None, logo_position_y=None,
	apps=None, migrations=None, business_processes=None, implementation_types=None, languages=None,
	founder=None, success_stories=None, addons=None,
	phone=None, team_size=None, journey_blog_url=None,
	logo=None, logo_icon=None, why_choose_them=None, origin_story=None, photos=None,
	how_we_work=None, successful_implementation=None, industries=None, delivery_options=None, as_draft=False,
):
	"""Lets the admin of the caller's own partner company edit their public profile —
	the same fields (and the same About / Success Stories / Pricing grouping) shown on the
	customer-facing partner profile page. Other members only read it. With `as_draft`, the
	changes wait in the partner's unpublished changes until publish_my_profile_draft."""
	partner = _my_admin_partner()

	# Fields Frappe or the frappe.io import own (partner_name, starter_pack, certificate counts, Starter
	# Pack prices, the imported numbers) are not parameters; frappe.call drops what a caller sends for them.
	changes = dict(
		tagline=tagline, description=description, country=country,
		city=city, address=address, website=website, year_founded=year_founded,
		hourly_rate=hourly_rate, typical_project_size=typical_project_size,
		proposal_timeline=proposal_timeline,
		demo_available=demo_available,
		logo_position_x=logo_position_x, logo_position_y=logo_position_y,
		phone=phone, team_size=team_size, journey_blog_url=journey_blog_url,
		logo=logo, logo_icon=logo_icon, why_choose_them=why_choose_them, origin_story=origin_story,
		how_we_work=how_we_work, successful_implementation=successful_implementation,
		apps=apps, migrations=migrations, business_processes=business_processes,
		implementation_types=implementation_types, languages=languages, industries=industries,
		delivery_options=delivery_options, founder=founder, success_stories=success_stories, photos=photos, addons=addons,
	)
	changes = {key: value for key, value in changes.items() if value is not None}

	doc, live = _edited_profile(partner, changes, with_draft=cint(as_draft))
	if not cint(as_draft):
		# Partners have no Desk write on Partner; _edited_profile found it through _my_admin_partner.
		doc.save(ignore_permissions=True)
		return {"partner": doc.name}

	# The draft isn't saved, so run the checks Partner.validate and link validation would.
	doc.validate_hourly_rate()
	doc.validate_country()
	validate_industries(doc)
	_save_profile_draft(live, doc)
	return {"partner": doc.name}


def publish_my_profile_draft() -> dict:
	"""Makes the admin's unpublished Listing changes live, checked again as any profile save is."""
	partner = _my_admin_partner()
	if not frappe.db.get_value("Partner", partner, "profile_draft"):
		frappe.throw(_("There are no unpublished changes to publish."))

	doc, _live = _edited_profile(partner, {}, with_draft=True)
	doc.profile_draft = None
	# As in update_my_partner_profile: _my_admin_partner stands in for Desk write on Partner.
	doc.save(ignore_permissions=True)
	return {"partner": doc.name}


def discard_my_profile_draft() -> dict:
	partner = _my_admin_partner()
	frappe.db.set_value("Partner", partner, "profile_draft", None, update_modified=False)
	return {"partner": partner}


def _my_admin_partner() -> str:
	partner = _my_partner()
	if not _is_partner_admin(partner, frappe.session.user):
		frappe.throw(_("Only your partner admin can edit the profile."), frappe.PermissionError)
	return partner


def _edited_profile(partner: str, changes: dict, with_draft: bool) -> tuple:
	"""The Partner with its unpublished changes (when asked) and `changes` applied, checked but not
	saved, and the live Partner it started from."""
	live = frappe.get_doc("Partner", partner)
	doc = frappe.get_doc("Partner", partner)
	if with_draft:
		_apply_profile_values(doc, _profile_draft(doc))

	_apply_profile_values(doc, changes)
	_check_profile_lengths(doc, live)
	_check_profile_media(doc)
	_check_gallery_size(doc, live)
	return doc, live


def _apply_profile_values(doc, values: dict) -> None:
	"""Sets the profile fields in `values`, shaped as update_my_partner_profile's arguments, on the
	Partner. Fields not in `values` keep what they have."""
	for fieldname in _PROFILE_SIMPLE_FIELDS:
		if fieldname in values:
			doc.set(fieldname, values[fieldname])

	for fieldname, child_field in _PROFILE_MULTISELECT_FIELDS.items():
		if fieldname in values:
			doc.set(fieldname, [{child_field: v} for v in _parse_json_arg(values[fieldname], [])])

	for fieldname, fields in _PROFILE_ROW_FIELDS.items():
		if fieldname in values:
			rows = _parse_json_arg(values[fieldname], [])
			doc.set(fieldname, [{field: row.get(field) for field in fields} for row in rows])

	_apply_founder(doc, _parse_json_arg(values.get("founder"), None))


def _apply_founder(doc, founder: dict | None) -> None:
	if not founder:
		return

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


def _profile_draft(doc) -> dict:
	return _parse_json_arg(doc.profile_draft, {}) or {}


def _save_profile_draft(live, doc) -> None:
	"""Keeps only what differs from the live profile, so publishing doesn't put back a value Frappe
	changed in the Desk since."""
	live_values = _profile_values(live)
	draft = {key: value for key, value in _profile_values(doc).items() if value != live_values[key]}
	# The live profile doesn't change, so its modified time doesn't either.
	frappe.db.set_value("Partner", live.name, "profile_draft", frappe.as_json(draft) if draft else None, update_modified=False)


def _profile_values(doc) -> dict:
	"""The profile shaped as update_my_partner_profile's arguments, cast so an unchanged field
	compares equal however it was set."""
	values = {fieldname: _plain_value(doc, fieldname) for fieldname in _PROFILE_SIMPLE_FIELDS}
	for fieldname, child_field in _PROFILE_MULTISELECT_FIELDS.items():
		values[fieldname] = [row.get(child_field) for row in doc.get(fieldname)]
	for fieldname, fields in _PROFILE_ROW_FIELDS.items():
		values[fieldname] = [{field: _plain_value(row, field) for field in fields} for row in doc.get(fieldname)]

	founder = next((row for row in doc.team if row.is_founder), None)
	values["founder"] = {field: _plain_value(founder, field) for field in _FOUNDER_FIELDS} if founder else {}
	return values


def _plain_value(row, fieldname):
	value = cast(row.meta.get_field(fieldname).fieldtype, row.get(fieldname))
	return "" if value is None else value
