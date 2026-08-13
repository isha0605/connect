import difflib
import json
import math
import re

import frappe
from frappe.utils import cint, flt, get_fullname, nowdate

PARTNER_FIELDS = [
	"name", "partner_name", "logo", "tagline", "tier", "specialist",
	"rating", "reviews_count", "industry", "country", "city", "rollouts",
]
SEARCHABLE_TEXT_FIELDS = ["partner_name", "tagline", "industry", "country", "city"]


def _fts_rank(search_term, allowed_names):
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


def _fuzzy_rank(search_term, candidates, threshold=0.65):
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


SORT_OPTIONS = {
	"rating_desc": ("rating", True),
	"rollouts_desc": ("rollouts", True),
	"name_asc": ("partner_name", False),
}


# Operators the CRM-style Filter component can emit (its own WIRE_OPERATOR map) —
# validated against this whitelist before reaching the query.
FILTER_OPERATORS = {"is", "is not", "in", "not in", "=", "!=", "like", "not like", ">", "<", ">=", "<=", "between", "timespan"}


@frappe.whitelist(allow_guest=True)
def search_partners(
	search=None, industry=None, product=None, region=None, delivery_mode=None, country=None,
	tier=None, business_process=None, implementation_type=None, language=None,
	min_rating=None, min_pmm_level=None, max_response_time=None,
	extra_filters=None,
	sort=None, limit=100,
):
	"""Guest-safe partner search backing the Find Partners page.

	Structured filters combine as AND and always run as a real DB query —
	`product`/`delivery_mode`/`business_process`/`implementation_type`/`language`
	filter through their Partner child tables via Frappe's built-in child-table
	join syntax (["<child doctype>", "<field>", "=", value]).

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
	# TEMPORARY: only surface the original curated (fully-profiled) partners
	# while the rest of the bulk-imported directory is still bare (name/tier/
	# country only, no logo/description/team). Remove this filter to bring the
	# full directory back — is_featured stays set on the underlying records.
	filters = [["Partner", "is_featured", "=", 1]]
	if industry:
		filters.append(["Partner", "industry", "=", industry])
	if region:
		filters.append(["Partner", "region", "=", region])
	if country:
		filters.append(["Partner", "country", "=", country])
	if product:
		filters.append(["Partner App", "app", "=", product])
	if delivery_mode:
		filters.append(["Partner Delivery Mode", "delivery_mode", "=", delivery_mode])
	if tier:
		filters.append(["Partner", "tier", "=", tier])
	if business_process:
		filters.append(["Partner Business Process", "business_process", "=", business_process])
	if implementation_type:
		filters.append(["Partner Implementation Type", "implementation_type", "=", implementation_type])
	if language:
		filters.append(["Partner Language", "language", "=", language])
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
	apps_by_partner = {}
	if partner_names:
		for row in frappe.get_all(
			"Partner App",
			filters={"parent": ["in", partner_names]},
			fields=["parent", "app"],
			order_by="idx asc",
		):
			bucket = apps_by_partner.setdefault(row.parent, [])
			if len(bucket) < 2:
				bucket.append(row.app)

	for p in partners:
		p["apps_preview"] = apps_by_partner.get(p.name, [])

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


@frappe.whitelist(allow_guest=True)
def count_matching_partners(answers=None):
	"""Live "partners that match so far" count for the finder wizard's dot-grid,
	recomputed cumulatively after every answer. Filters combine as AND, narrowing
	as more (mappable) answers come in — only questions with a real mapping to
	Partner data affect the count."""
	if isinstance(answers, str):
		answers = json.loads(answers or "{}")
	answers = answers or {}
	# Same temporary is_featured scope as search_partners, so the wizard's live
	# count never exceeds what the directory actually shows right now.
	filters = [["Partner", "is_featured", "=", 1]]

	industry = answers.get("industry")
	if industry:
		filters.append(["Partner", "industry", "=", WIZARD_TO_PARTNER_INDUSTRY.get(industry, industry)])

	impl_type = LOOKING_FOR_TO_IMPL_TYPE.get(answers.get("looking_for"))
	if impl_type:
		filters.append(["Partner Implementation Type", "implementation_type", "=", impl_type])

	situation = answers.get("current_situation")
	migration = CURRENT_SITUATION_TO_MIGRATION.get(situation)
	if migration:
		filters.append(["Partner Migration Path", "migration_path", "=", migration])
	else:
		impl_type_2 = CURRENT_SITUATION_TO_IMPL_TYPE.get(situation)
		if impl_type_2:
			filters.append(["Partner Implementation Type", "implementation_type", "=", impl_type_2])

	mode = DELIVERY_TO_MODE.get(answers.get("delivery_preference"))
	if mode:
		filters.append(["Partner Delivery Mode", "delivery_mode", "=", mode])

	requirements = answers.get("requirements") or []
	bp_values = [REQUIREMENT_TO_BUSINESS_PROCESS[r] for r in requirements if r in REQUIREMENT_TO_BUSINESS_PROCESS]
	if bp_values:
		filters.append(["Partner Business Process", "business_process", "in", bp_values])
	elif any(r in REQUIREMENT_MIGRATION_TAGS for r in requirements):
		filters.append(["Partner Migration Path", "migration_path", "is", "set"])

	# limit_page_length=0: frappe.get_list defaults to page size 20 when omitted.
	partners = frappe.get_list("Partner", filters=filters, fields=["name"], limit_page_length=0)
	return len(partners)


# Per-question matcher tables for the wizard's live dot-elimination pictogram
# (wizard_match_state). Each maps an option VALUE to a (partner_row) -> bool
# predicate grounded in real Partner data. A value with no defensible signal is
# simply absent from its table, so wizard_match_state leaves the pool untouched
# for that answer instead of guessing.
NEED_MATCHERS = {
	"Replace Existing ERP": lambda p: len(p["migrations"]) > 0,
	"Manufacturing Setup": lambda p: p["industry"] == "Manufacturing",
	"HR & Payroll": lambda p: any("hr" in a.lower() for a in p["apps"]),
	"CRM": lambda p: any("crm" in a.lower() for a in p["apps"]),
	"Custom App Development": lambda p: "Customization" in p["implementation_types"],
	"Consultation / Discovery": lambda p: p["demo_available"],
}
COMPANY_SIZE_TO_BUCKET = {
	"1–10": "Small", "11–50": "Small", "51–200": "Mid-size", "201–1000": "Mid-size", "1000+": "Large",
}
CURRENT_SYSTEM_MATCHERS = {
	"Excel / Spreadsheets": lambda p: any(m.startswith("Excel") for m in p["migrations"]),
	"Tally": lambda p: any(m.startswith("Tally") for m in p["migrations"]),
	"SAP": lambda p: any(m.startswith("SAP") for m in p["migrations"]),
	"Odoo": lambda p: any(m.startswith("Odoo") for m in p["migrations"]),
	"Existing ERPNext": lambda p: len(p["migrations"]) == 0,
	"Multiple Systems": lambda p: len(p["migrations"]) >= 1,
}
TIMELINE_MATCHERS = {
	# response_time_hours == 0 means "not profiled", not "instant" -- excluded explicitly
	# so an unprofiled partner isn't falsely counted as meeting an urgent timeline.
	"Immediately": lambda p: bool(p["response_time_hours"]) and p["response_time_hours"] <= 12,
	"Within 1 month": lambda p: bool(p["response_time_hours"]) and p["response_time_hours"] <= 24,
}
BUDGET_TO_TIERS = {
	"Under ₹2L": {"Bronze"},
	"₹2L–₹10L": {"Bronze", "Silver"},
	"₹10L–₹25L": {"Silver"},
	"₹25L–₹50L": {"Silver", "Gold"},
	"₹50L+": {"Gold"},
}
REQUIREMENT_MATCHERS = {
	"ETO (Engineer-to-Order)": lambda p: "Manufacturing Execution" in p["business_processes"],
	"Manufacturing Planning": lambda p: "Manufacturing Execution" in p["business_processes"],
	"HR & Payroll": lambda p: "HR & Payroll" in p["business_processes"],
	"Inventory Management": lambda p: "Inventory Management" in p["business_processes"],
	"CRM": lambda p: any("crm" in a.lower() for a in p["apps"]),
	"Custom Development": lambda p: "Customization" in p["implementation_types"],
	"SAP Migration": lambda p: any(m.startswith("SAP") for m in p["migrations"]),
	"Data Migration": lambda p: len(p["migrations"]) > 0,
	"On-site Support": lambda p: "Onsite" in p["delivery_options"],
	# "Multi-site Operations" and "Training Required" have no real signal in the
	# current schema -- deliberately absent rather than guessed at.
}


def _bucket_project_size(raw):
	"""'$15k - $60k' -> 'Small'/'Mid-size'/'Large', or None if unparseable/unset."""
	if not raw:
		return None
	nums = [int(n) for n in re.findall(r"(\d+)k", raw)]
	if not nums:
		return None
	upper = max(nums)
	if upper <= 25:
		return "Small"
	if upper <= 100:
		return "Mid-size"
	return "Large"


def _apply_matcher(pool, predicate):
	"""Never let a single criterion empty the pool -- if nothing in the current
	pool satisfies it, skip it for this preview rather than showing zero."""
	if predicate is None:
		return pool
	matched = [p for p in pool if predicate(p)]
	return matched if matched else pool


@frappe.whitelist(allow_guest=True)
def wizard_match_state(answers=None):
	"""Live per-partner matched/eliminated state for the finder wizard's dot
	pictogram. Applies all answered criteria in question order, each one a no-op
	if it would empty the pool, then a proportional quality trim (keeping the
	highest-rated partners) so every answered question visibly moves the count
	even ones with no category matcher — same idea as count_matching_partners,
	but returns which partners survived, not just how many."""
	if isinstance(answers, str):
		answers = json.loads(answers or "{}")
	answers = answers or {}

	names = [n.name for n in frappe.get_list(
		"Partner", filters=[["Partner", "is_featured", "=", 1]], fields=["name"], limit_page_length=0,
	)]
	if not names:
		return {"matched_names": [], "count": 0}

	rows = frappe.get_list(
		"Partner", filters=[["Partner", "name", "in", names]],
		fields=["name", "industry", "tier", "rating", "demo_available", "response_time_hours", "typical_project_size"],
	)
	apps_by, migrations_by, impl_by, bp_by, delivery_by = {}, {}, {}, {}, {}
	for r in frappe.get_all("Partner App", filters={"parent": ["in", names]}, fields=["parent", "app"]):
		apps_by.setdefault(r.parent, []).append(r.app)
	for r in frappe.get_all("Partner Migration Path", filters={"parent": ["in", names]}, fields=["parent", "migration_path"]):
		migrations_by.setdefault(r.parent, []).append(r.migration_path)
	for r in frappe.get_all("Partner Implementation Type", filters={"parent": ["in", names]}, fields=["parent", "implementation_type"]):
		impl_by.setdefault(r.parent, []).append(r.implementation_type)
	for r in frappe.get_all("Partner Business Process", filters={"parent": ["in", names]}, fields=["parent", "business_process"]):
		bp_by.setdefault(r.parent, []).append(r.business_process)
	for r in frappe.get_all("Partner Delivery Mode", filters={"parent": ["in", names]}, fields=["parent", "delivery_mode"]):
		delivery_by.setdefault(r.parent, []).append(r.delivery_mode)

	pool = [{
		"name": r.name, "industry": r.industry, "tier": r.tier, "rating": r.rating or 0,
		"demo_available": bool(r.demo_available),
		"response_time_hours": r.response_time_hours or 0,
		"project_size_bucket": _bucket_project_size(r.typical_project_size),
		"apps": apps_by.get(r.name, []),
		"migrations": migrations_by.get(r.name, []),
		"implementation_types": impl_by.get(r.name, []),
		"business_processes": bp_by.get(r.name, []),
		"delivery_options": delivery_by.get(r.name, []),
	} for r in rows]

	need = answers.get("looking_for")
	pool = _apply_matcher(pool, NEED_MATCHERS.get(need))

	industry = answers.get("industry")
	if industry:
		wanted = WIZARD_TO_PARTNER_INDUSTRY.get(industry, industry)
		pool = _apply_matcher(pool, lambda p, w=wanted: p["industry"] == w)

	bucket = COMPANY_SIZE_TO_BUCKET.get(answers.get("company_size"))
	if bucket:
		pool = _apply_matcher(pool, lambda p, b=bucket: p["project_size_bucket"] == b)

	pool = _apply_matcher(pool, CURRENT_SYSTEM_MATCHERS.get(answers.get("current_situation")))
	pool = _apply_matcher(pool, TIMELINE_MATCHERS.get(answers.get("timeline")))

	delivery = answers.get("delivery_preference")
	if delivery and delivery != "No preference":
		wanted_mode = DELIVERY_TO_MODE.get(delivery, delivery)
		pool = _apply_matcher(pool, lambda p, w=wanted_mode: w in p["delivery_options"])

	tiers = BUDGET_TO_TIERS.get(answers.get("budget"))
	if tiers:
		pool = _apply_matcher(pool, lambda p, t=tiers: p["tier"] in t)

	for req in (answers.get("requirements") or []):
		pool = _apply_matcher(pool, REQUIREMENT_MATCHERS.get(req))

	# Proportional quality trim: every answered question should visibly move
	# the count, even ones above with no real matcher for this particular value.
	answered = sum(
		1 for k in ("looking_for", "industry", "company_size", "current_situation", "timeline", "delivery_preference", "budget")
		if answers.get(k)
	)
	if answers.get("requirements"):
		answered += 1
	if answered and pool:
		target = max(1, math.ceil(len(pool) * (0.85**answered)))
		pool = sorted(pool, key=lambda p: -p["rating"])[:target]

	return {"matched_names": [p["name"] for p in pool], "count": len(pool)}


@frappe.whitelist(allow_guest=True)
def list_matching_partners(answers=None, limit=8):
	"""Ranked partner results for the finder wizard's final step. Same real
	wizard-answer -> Partner-data mappings as count_matching_partners, but returns
	full rows (same shape as search_partners) instead of just a count.

	Every is_featured partner is scored by how many of a small set of concrete,
	customer-recognizable requirements they fail (currently: industry, delivery
	mode) — not a hard AND filter. Full matches (0 missed) come first; partners
	missing 1-2 requirements are included after with `missing_label` naming
	exactly what they're short on, so a strong-but-imperfect match doesn't just
	disappear. Partners missing 3+ are excluded as too far off to be useful."""
	if isinstance(answers, str):
		answers = json.loads(answers or "{}")
	answers = answers or {}
	limit = cint(limit) or 8

	names = [n.name for n in frappe.get_list(
		"Partner", filters=[["Partner", "is_featured", "=", 1]], fields=["name"], limit_page_length=0,
	)]
	if not names:
		return []

	rows = frappe.get_list("Partner", filters=[["Partner", "name", "in", names]], fields=PARTNER_FIELDS)
	by_name = {r.name: r for r in rows}

	delivery_by = {}
	for r in frappe.get_all("Partner Delivery Mode", filters={"parent": ["in", names]}, fields=["parent", "delivery_mode"]):
		delivery_by.setdefault(r.parent, []).append(r.delivery_mode)

	apps_by_partner = {}
	for row in frappe.get_all(
		"Partner App", filters={"parent": ["in", names]}, fields=["parent", "app"], order_by="idx asc",
	):
		bucket = apps_by_partner.setdefault(row.parent, [])
		if len(bucket) < 2:
			bucket.append(row.app)

	industry = answers.get("industry")
	wanted_industry = WIZARD_TO_PARTNER_INDUSTRY.get(industry, industry) if industry else None

	delivery = answers.get("delivery_preference")
	wanted_mode = DELIVERY_TO_MODE.get(delivery) if delivery and delivery != "No preference" else None

	scored = []
	for name in names:
		row = by_name.get(name)
		if not row:
			continue
		missing = []
		if wanted_industry and row.industry != wanted_industry:
			missing.append(f"{industry} Experience")
		if wanted_mode and wanted_mode not in delivery_by.get(name, []):
			missing.append(f"{delivery} Delivery")
		if len(missing) <= 2:
			scored.append((len(missing), -(row.rating or 0), name, missing))

	scored.sort(key=lambda s: (s[0], s[1]))
	scored = scored[:limit]

	result = []
	for _missing_count, _neg_rating, name, missing in scored:
		row = dict(by_name[name])
		row["apps_preview"] = apps_by_partner.get(name, [])
		row["missing_label"] = ", ".join(missing) if missing else None
		result.append(row)
	return result


@frappe.whitelist(allow_guest=True)
def list_partner_countries():
	"""Distinct countries with at least one Partner, for the Country filter dropdown.

	Document List resources can't express DISTINCT, so this is a small API
	Resource instead — mirrors search_partners in spirit.
	"""
	rows = frappe.get_all(
		"Partner", fields=["country"], filters={"country": ["is", "set"], "is_featured": 1}, distinct=True
	)
	return sorted({row.country for row in rows if row.country})


@frappe.whitelist(allow_guest=True)
def list_partner_filter_options():
	"""Option lists for the Find Partners filter panel's Business Process /
	Implementation Type / Language dropdowns. Studio's "Document List" resource
	type calls frappe.client.get_list under the hood, which isn't guest-whitelisted
	regardless of the target doctype's own Guest permission — so those dropdowns
	silently returned nothing for guest visitors. This is a small API Resource
	instead, same fix as list_partner_countries above."""
	return {
		"business_processes": frappe.get_all("Business Process", pluck="title", order_by="title"),
		"implementation_types": frappe.get_all("Implementation Type", pluck="title", order_by="title"),
		"languages": frappe.get_all("FC Language", pluck="title", order_by="title"),
	}


def _get_customer_for_user(user=None):
	"""Customer company the given (or current session) user belongs to, via Customer Team Member."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return None
	return frappe.db.get_value("Customer Team Member", {"user": user}, "parent")


@frappe.whitelist()
def get_my_customer():
	"""Current session user's Customer company — feeds the portal shell (sidebar identity etc)."""
	customer = _get_customer_for_user()
	if not customer:
		return None
	return frappe.db.get_value("Customer", customer, ["name", "customer_name"], as_dict=True)


@frappe.whitelist()
def get_my_shortlisted_partner_names():
	"""Lightweight list of shortlisted partner names for the current user's company —
	used to mark bookmark state on Find Partners without re-fetching full partner rows."""
	customer = _get_customer_for_user()
	if not customer:
		return []
	return frappe.get_all("Shortlist", filters={"customer": customer}, pluck="partner")


@frappe.whitelist()
def add_to_shortlist(partner):
	customer = _get_customer_for_user()
	if not customer:
		frappe.throw("Your account isn't linked to a customer company yet.", frappe.PermissionError)
	if not frappe.db.exists("Shortlist", {"customer": customer, "partner": partner}):
		frappe.get_doc({"doctype": "Shortlist", "customer": customer, "partner": partner}).insert(
			ignore_permissions=True
		)
		frappe.db.commit()
	return {"shortlisted": True}


@frappe.whitelist()
def remove_from_shortlist(partner):
	customer = _get_customer_for_user()
	if not customer:
		frappe.throw("Your account isn't linked to a customer company yet.", frappe.PermissionError)
	existing = frappe.db.get_value("Shortlist", {"customer": customer, "partner": partner})
	if existing:
		frappe.delete_doc("Shortlist", existing, ignore_permissions=True)
		frappe.db.commit()
	return {"shortlisted": False}


@frappe.whitelist()
def list_my_shortlist():
	"""Full Partner records the current user's company has shortlisted — backs the Shortlisted page."""
	customer = _get_customer_for_user()
	if not customer:
		return []
	rows = frappe.get_all(
		"Shortlist", filters={"customer": customer}, fields=["partner"], order_by="creation desc"
	)
	names = [r.partner for r in rows]
	if not names:
		return []

	partners = frappe.get_list("Partner", fields=PARTNER_FIELDS, filters={"name": ["in", names]})
	by_name = {p.name: p for p in partners}
	ordered = [by_name[n] for n in names if n in by_name]

	apps_by_partner = {}
	for row in frappe.get_all(
		"Partner App", filters={"parent": ["in", names]}, fields=["parent", "app"], order_by="idx asc"
	):
		bucket = apps_by_partner.setdefault(row.parent, [])
		if len(bucket) < 2:
			bucket.append(row.app)
	for p in ordered:
		p["apps_preview"] = apps_by_partner.get(p.name, [])

	return ordered


@frappe.whitelist()
def save_customer_requirement(
	looking_for, industry, company_size, current_situation, timeline, delivery_preference, budget,
	special_requirements=None, outcome=None,
):
	"""Persist one completed "Find me a partner" wizard run for the current user's company."""
	customer = _get_customer_for_user()
	if not customer:
		frappe.throw("Your account isn't linked to a customer company yet.", frappe.PermissionError)

	doc = frappe.get_doc({
		"doctype": "Requirement",
		"customer": customer,
		"looking_for": looking_for,
		"industry": industry,
		"company_size": company_size,
		"current_situation": current_situation,
		"timeline": timeline,
		"delivery_preference": delivery_preference,
		"budget": budget,
		"special_requirements": special_requirements or "[]",
		"outcome": outcome,
	})
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def get_my_review_for_partner(partner):
	"""The current user's own review of this partner, if they've already left one —
	lets the "Write a Review" form load as an edit instead of a blank form."""
	customer = _get_customer_for_user()
	if not customer:
		return None
	name = frappe.db.get_value("Partner Review", {"partner": partner, "customer": customer}, "name")
	return frappe.get_doc("Partner Review", name).as_dict() if name else None


@frappe.whitelist()
def submit_partner_review(
	partner, rating, headline=None, quote=None,
	business_understanding=None, implementation_quality=None, communication=None,
	timeliness=None, support=None, technical_expertise=None,
):
	"""Create or update the current customer's review of a partner. Partner.rating,
	reviews_count, and the dimension scores are recomputed by Partner Review's own
	after_insert/on_update hook, not here."""
	customer = _get_customer_for_user()
	if not customer:
		frappe.throw("Your account isn't linked to a customer company yet.", frappe.PermissionError)

	rating = cint(rating)
	if rating < 1 or rating > 5:
		frappe.throw("Rating must be between 1 and 5.")

	values = {
		"partner": partner,
		"customer": customer,
		"reviewer_name": get_fullname(frappe.session.user),
		"rating": rating,
		"headline": headline,
		"quote": quote,
		"reviewed_on": nowdate(),
		"verified": 1,
		"business_understanding": cint(business_understanding) or None,
		"implementation_quality": cint(implementation_quality) or None,
		"communication": cint(communication) or None,
		"timeliness": cint(timeliness) or None,
		"support": cint(support) or None,
		"technical_expertise": cint(technical_expertise) or None,
	}

	existing = frappe.db.get_value("Partner Review", {"partner": partner, "customer": customer}, "name")
	if existing:
		doc = frappe.get_doc("Partner Review", existing)
		doc.update(values)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "Partner Review", **values})
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
	return {"name": doc.name}
