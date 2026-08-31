import difflib
import json
import math
import os

import frappe
from frappe import _
from frappe.utils import cint, flt, get_fullname, now_datetime, nowdate, validate_email_address
from pypika.functions import DistinctOptionFunction
from pypika.utils import builder

from connect.permissions import _is_customer_admin, _is_partner_admin, _my_company_membership



@frappe.whitelist()
def get_my_company_members():
	"""Returns the caller's own company roster, used to populate the "transfer admin to" picker."""
	user = frappe.session.user
	doctype, company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	fieldname = "customer" if doctype == "Customer Team Member" else "partner"
	return frappe.get_all(doctype, filters={fieldname: company}, fields=["user", "is_admin"])


@frappe.whitelist()
def get_my_team():
	"""Returns the caller's own company roster with names and photos, to render the Settings Users list."""
	user = frappe.session.user
	doctype, company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	fieldname = "customer" if doctype == "Customer Team Member" else "partner"
	role_field = "designation" if doctype == "Customer Team Member" else "role"

	Member = frappe.qb.DocType(doctype)
	UserTable = frappe.qb.DocType("User")
	return (
		frappe.qb.from_(Member)
		.left_join(UserTable)
		.on(Member.user == UserTable.name)
		.select(
			Member.name, Member.user, Member.is_admin, Member.is_removed,
			Member[role_field].as_("role"), UserTable.full_name, UserTable.user_image,
		)
		.where(Member[fieldname] == company)
		.orderby(Member.is_admin, order=frappe.qb.desc)
		.orderby(Member.creation, order=frappe.qb.asc)
		.run(as_dict=True)
	)


@frappe.whitelist()
def remove_team_member(member):
	"""Removes someone from the caller's own company roster, on whichever side the caller belongs to."""
	user = frappe.session.user
	doctype, _company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	doc = frappe.get_doc(doctype, member)
	doc.remove(user)
	return {"removed": doc.user}


@frappe.whitelist()
def add_team_member(email, role=None, password=None):
	"""Invites someone onto the caller's own company roster, creating their user account first if it doesn't exist."""
	user = frappe.session.user
	doctype, company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	is_customer_side = doctype == "Customer Team Member"
	authorized = (
		_is_customer_admin(company, user) if is_customer_side else _is_partner_admin(company, user)
	)
	if not authorized:
		frappe.throw(_("Only an admin can add a team member"), frappe.PermissionError)

	email = (email or "").strip().lower()
	if not email:
		frappe.throw(_("Enter an email address"))
	if not validate_email_address(email, throw=False):
		frappe.throw(_("Enter a valid email address"))

	fieldname = "customer" if is_customer_side else "partner"
	if frappe.db.exists(doctype, {fieldname: company, "user": email}):
		frappe.throw(_("{0} is already a member").format(email))

	created_user = False
	if not frappe.db.exists("User", email):
		new_user = frappe.new_doc("User")
		new_user.email = email
		new_user.first_name = email.split("@")[0]
		new_user.user_type = "Website User"
		new_user.send_welcome_email = 0
		if password:
			new_user.new_password = password
		new_user.insert(ignore_permissions=True)
		created_user = True

	role_field = "designation" if is_customer_side else "role"
	member_doc = frappe.get_doc({
		"doctype": doctype,
		fieldname: company,
		"user": email,
		"is_admin": 0,
		role_field: role,
	})
	member_doc.insert(ignore_permissions=True)

	return {"member": member_doc.name, "created_user": created_user}


@frappe.whitelist()
def get_my_profile():
	"""Returns the caller's own name, photo, and contact details for the sidebar avatar and Settings Profile section."""
	user = frappe.session.user
	UserTable = frappe.qb.DocType("User")
	PartnerMember = frappe.qb.DocType("Connect Partner Member")
	rows = (
		frappe.qb.from_(UserTable)
		.left_join(PartnerMember)
		.on(PartnerMember.user == UserTable.name)
		.select(UserTable.full_name, UserTable.user_image, UserTable.phone, PartnerMember.role)
		.where(UserTable.name == user)
		.run(as_dict=True)
	)
	profile = rows[0] if rows else {}
	return {
		"email": user,
		"full_name": profile.get("full_name"),
		"user_image": profile.get("user_image"),
		"phone": profile.get("phone"),
		"role": profile.get("role"),
	}


@frappe.whitelist()
def update_my_profile(full_name, phone=None, role=None):
	"""Lets any logged-in user edit their own profile details."""
	full_name = (full_name or "").strip()
	if not full_name:
		frappe.throw(_("Name can't be empty"))

	user = frappe.session.user
	frappe.db.set_value("User", user, {"full_name": full_name, "phone": (phone or "").strip()})

	member_name = frappe.db.get_value("Connect Partner Member", {"user": user}, "name")
	if member_name:
		frappe.db.set_value("Connect Partner Member", member_name, "role", (role or "").strip())

	return {"email": user, "full_name": full_name}


ALLOWED_PROFILE_IMAGE_EXTENSIONS = {
	".png": "image/png",
	".jpg": "image/jpeg",
	".jpeg": "image/jpeg",
	".gif": "image/gif",
	".webp": "image/webp",
}
MAX_PROFILE_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB


@frappe.whitelist()
def upload_profile_image():
	"""Sets the caller's own profile photo from an uploaded image, stored publicly since avatars are shown to other users."""
	uploaded = frappe.request.files.get("file") if frappe.request else None
	if not uploaded:
		frappe.throw(_("No file was uploaded"))

	filename = uploaded.filename or ""
	ext = os.path.splitext(filename)[1].lower()
	if ext not in ALLOWED_PROFILE_IMAGE_EXTENSIONS:
		frappe.throw(_("Only PNG, JPG, GIF, and WEBP images can be used as a profile photo"))

	content = uploaded.stream.read()
	if len(content) > MAX_PROFILE_IMAGE_SIZE:
		frappe.throw(
			_("Image is too large — the limit is {0} MB").format(MAX_PROFILE_IMAGE_SIZE // (1024 * 1024))
		)

	user = frappe.session.user
	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": filename,
		"content": content,
		"is_private": 0,
		"attached_to_doctype": "User",
		"attached_to_name": user,
		"attached_to_field": "user_image",
	})
	file_doc.insert(ignore_permissions=True)

	frappe.db.set_value("User", user, "user_image", file_doc.file_url)
	return {"user_image": file_doc.file_url}


@frappe.whitelist(allow_guest=True)
def get_my_context():
	"""Returns the caller's customer or partner company membership, or nulls for a guest."""
	user = frappe.session.user
	customer = _get_customer_for_user(user)
	customer_membership = None
	if customer:
		is_admin = frappe.db.get_value("Customer Team Member", {"customer": customer, "user": user}, "is_admin")
		customer_name = frappe.db.get_value("Customer", customer, "customer_name")
		customer_membership = {"customer": customer, "customer_name": customer_name, "is_admin": cint(is_admin)}
	partner_membership = frappe.db.get_value(
		"Connect Partner Member", {"user": user}, ["partner", "is_admin"], as_dict=True
	)
	if partner_membership:
		partner_membership["partner_name"] = frappe.db.get_value("Partner", partner_membership.partner, "partner_name")
	return {
		"user": user,
		"customer": customer_membership,
		"partner": partner_membership,
	}


@frappe.whitelist(allow_guest=True)
def signup_customer(full_name, company_name, email, password):
	"""Lets a new customer self-signup by creating their user, company, and admin membership in one step."""
	full_name = (full_name or "").strip()
	company_name = (company_name or "").strip()
	email = (email or "").strip().lower()
	if not full_name or not company_name or not email or not password:
		frappe.throw(_("Please fill in all fields"))
	if not validate_email_address(email, throw=False):
		frappe.throw(_("Enter a valid email address"))
	if frappe.db.exists("User", email):
		frappe.throw(_("An account with this email already exists. Log in instead."))
	if frappe.db.exists("Customer", company_name):
		frappe.throw(
			_("{0} is already registered. Ask your team admin to add you instead.").format(company_name)
		)

	first_name, _, last_name = full_name.partition(" ")

	user = frappe.new_doc("User")
	user.email = email
	user.first_name = first_name
	user.last_name = last_name
	user.user_type = "Website User"
	user.send_welcome_email = 0
	user.new_password = password
	user.insert(ignore_permissions=True)

	customer = frappe.new_doc("Customer")
	customer.customer_name = company_name
	customer.insert(ignore_permissions=True)

	frappe.get_doc({
		"doctype": "Customer Team Member",
		"customer": customer.name,
		"user": email,
		"full_name": full_name,
		"is_admin": 1,
	}).insert(ignore_permissions=True)

	frappe.local.login_manager.login_as(email)
	return {"ok": True}


PARTNER_FIELDS = [
	"name", "partner_name", "logo", "tagline", "tier", "specialist",
	"rating", "reviews_count", "industry", "country", "city", "rollouts", "hourly_rate",
	"response_time_hours",
]
SEARCHABLE_TEXT_FIELDS = ["partner_name", "tagline", "industry", "country", "city"]

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


class _NaturalLanguageMatch(DistinctOptionFunction):
	"""A multi-column MATCH()/AGAINST() function, since frappe's built-in Match only supports one column."""

	def __init__(self, *columns):
		super().__init__("MATCH", *columns)
		self._against = None

	def get_function_sql(self, **kwargs):
		sql = super(DistinctOptionFunction, self).get_function_sql(**kwargs)
		if self._against is None:
			raise Exception("Chain the `Against()` method with match to complete the query")
		return f"{sql} AGAINST ({frappe.db.escape(self._against)} IN NATURAL LANGUAGE MODE)"

	@builder
	def Against(self, text):
		self._against = text


def _fts_rank(search_term, allowed_names):
	"""Ranks partner names by MariaDB full-text search relevance against the search term."""
	if not allowed_names:
		return []
	Partner = frappe.qb.DocType("Partner")
	rank = _NaturalLanguageMatch(
		Partner.partner_name, Partner.tagline, Partner.description,
		Partner.industry, Partner.city, Partner.country,
	).Against(search_term)
	rows = (
		frappe.qb.from_(Partner)
		.select(Partner.name, rank.as_("rank"))
		.where(Partner.name.isin(allowed_names))
		.where(rank)
		.orderby("rank", order=frappe.qb.desc)
	).run(as_dict=True)
	return [r.name for r in rows]


def _fuzzy_rank(search_term, candidates, threshold=0.65):
	"""Ranks partners by typo-tolerant fuzzy match, as a fallback for terms full-text search misses."""
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
	]:
		if value:
			child_matches.append(_partners_matching_child(doctype, field, "=", value, parentfield=parentfield))
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


@frappe.whitelist(allow_guest=True)
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


@frappe.whitelist(allow_guest=True)
def wizard_match_state(answers=None):
	"""Returns exact-match partner names and count for the finder wizard's dot pictogram."""
	answers = _parse_answers(answers)

	all_scored, _apps_by_partner, _answered_dims = _score_partners_by_requirements(answers)
	exact = [s for s in all_scored if s[0] == 0]
	matched_names = [name for *_rest, name, _missing in exact]
	return {"matched_names": matched_names, "count": len(matched_names)}


@frappe.whitelist(allow_guest=True)
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


@frappe.whitelist(allow_guest=True)
def list_partner_countries():
	"""Returns distinct countries with at least one partner, for the Country filter dropdown."""
	rows = frappe.get_all(
		"Partner", fields=["country"], filters={"country": ["is", "set"], "is_featured": 1, "enabled": 1}, distinct=True
	)
	return sorted({row.country for row in rows if row.country})


@frappe.whitelist(allow_guest=True)
def list_partner_filter_options():
	"""Returns filter dropdown options as a plain API call, since Studio's Document List resource isn't guest-accessible."""
	return {
		"business_processes": frappe.get_all("Business Process", pluck="title", order_by="title"),
		"implementation_types": frappe.get_all("Implementation Type", pluck="title", order_by="title"),
		"languages": frappe.get_all("FC Language", pluck="title", order_by="title"),
		"apps": frappe.get_all("App", pluck="title", order_by="title"),
	}


def _get_customer_for_user(user=None):
	"""Customer company the given (or current session) user belongs to, via Customer Team Member."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return None
	return frappe.db.get_value("Customer Team Member", {"user": user}, "customer")


REQUIREMENT_FIELDS = [
	"name", "company_name", "country", "industry", "looking_for", "company_size",
	"current_situation", "timeline", "delivery_preference", "budget",
	"special_requirements", "additional_notes",
]


def _latest_requirement_for_customer(customer):
	"""The customer's most recent Requirement row plus its apps, in 2 queries total — just the
	fields get_my_requirement/get_requirement_snapshot actually return. frappe.get_doc(...) would
	cost one query for every column on the doctype (not just the ~12 used here) plus one query per
	child table it defines, whether read or not."""
	RequirementTable = frappe.qb.DocType("Requirement")
	rows = (
		frappe.qb.from_(RequirementTable)
		.select(*[RequirementTable[f] for f in REQUIREMENT_FIELDS])
		.where(RequirementTable.customer == customer)
		.orderby(RequirementTable.creation, order=frappe.qb.desc)
		.limit(1)
		.run(as_dict=True)
	)
	if not rows:
		return None
	req = rows[0]

	AppTable = frappe.qb.DocType("Partner App")
	req["apps"] = (
		frappe.qb.from_(AppTable)
		.select(AppTable.app)
		.where(
			(AppTable.parent == req.name)
			& (AppTable.parenttype == "Requirement")
			& (AppTable.parentfield == "apps")
		)
		.orderby(AppTable.idx)
		.run(pluck=True)
	)
	return req


@frappe.whitelist(allow_guest=True)
def get_my_customer():
	"""Current session user's Customer company — feeds the portal shell (sidebar identity etc)."""
	customer = _get_customer_for_user()
	if not customer:
		return None
	return frappe.db.get_value("Customer", customer, ["name", "customer_name"], as_dict=True)


@frappe.whitelist(allow_guest=True)
def get_my_shortlisted_partner_names():
	"""Returns the current user's shortlisted partner names, to mark bookmark state without refetching full partner data."""
	customer = _get_customer_for_user()
	if not customer:
		return []
	return frappe.get_all("Shortlist", filters={"customer": customer}, pluck="partner")


@frappe.whitelist()
def add_to_shortlist(partner):
	"""Idempotent: a second call for an already-shortlisted partner is a silent no-op rather than
	an error, matching the UI's bookmark-toggle semantics. Relies on the (customer, partner)
	unique constraint on Shortlist (see connect.patches.add_shortlist_unique_constraint) to
	reject a duplicate instead of checking for one first."""
	customer = _get_customer_for_user()
	if not customer:
		frappe.throw("Your account isn't linked to a customer company yet.", frappe.PermissionError)
	try:
		frappe.get_doc({"doctype": "Shortlist", "customer": customer, "partner": partner}).insert(
			ignore_permissions=True
		)
	except frappe.UniqueValidationError:
		pass
	return {"shortlisted": True}


@frappe.whitelist()
def remove_from_shortlist(partner):
	customer = _get_customer_for_user()
	if not customer:
		frappe.throw("Your account isn't linked to a customer company yet.", frappe.PermissionError)
	existing = frappe.db.get_value("Shortlist", {"customer": customer, "partner": partner})
	if existing:
		frappe.delete_doc("Shortlist", existing, ignore_permissions=True)
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

	apps_by_partner = _apps_by_partner(names)
	for p in ordered:
		p["apps_preview"] = apps_by_partner.get(p.name, [])[:2]

	attach_success_story_previews(ordered)
	return ordered


@frappe.whitelist()
def save_customer_requirement(
	country, industry, apps=None,
	looking_for=None, company_size=None, current_situation=None, timeline=None, delivery_preference=None, budget=None,
	special_requirements=None, additional_notes=None, outcome=None,
):
	"""Creates or updates the caller's one Requirement, so the wizard and the Settings form share a single saved
	record. company_name isn't a parameter here — it's already collected at signup (Customer.customer_name),
	so it's read from there instead of asking again."""
	customer = _get_customer_for_user()
	if not customer:
		frappe.throw("Your account isn't linked to a customer company yet.", frappe.PermissionError)

	if isinstance(apps, str):
		apps = json.loads(apps or "[]")

	values = {
		"customer": customer,
		"company_name": frappe.db.get_value("Customer", customer, "customer_name"),
		"country": country,
		"industry": industry,
		"apps": [{"app": a} for a in (apps or [])],
		"looking_for": looking_for,
		"company_size": company_size,
		"current_situation": current_situation,
		"timeline": timeline,
		"delivery_preference": delivery_preference,
		"budget": budget,
		"special_requirements": special_requirements or "[]",
		"additional_notes": additional_notes or "",
	}
	if outcome:
		values["outcome"] = outcome

	existing = frappe.db.get_value("Requirement", {"customer": customer}, "name", order_by="creation desc")
	if existing:
		doc = frappe.get_doc("Requirement", existing)
		doc.update(values)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "Requirement", **values})
		doc.insert(ignore_permissions=True)

	return {"name": doc.name}


@frappe.whitelist(allow_guest=True)
def get_my_requirement():
	"""Returns the caller's saved Requirement to prefill the Settings "Edit Requirements" form."""
	customer = _get_customer_for_user()
	if not customer:
		return None
	req = _latest_requirement_for_customer(customer)
	if not req:
		return None
	return {
		"name": req.name,
		"company_name": req.company_name,
		"country": req.country,
		"industry": req.industry,
		"apps": req.apps,
		"looking_for": req.looking_for,
		"company_size": req.company_size,
		"current_situation": req.current_situation,
		"timeline": req.timeline,
		"delivery_preference": req.delivery_preference,
		"budget": req.budget,
		"special_requirements": req.special_requirements,
		"additional_notes": req.additional_notes,
	}


@frappe.whitelist(allow_guest=True)
def get_partner_preview(partner):
	"""Returns a lightweight partner snapshot for the quick-preview drawer, fetched only when needed."""
	fields = [
		"name", "partner_name", "logo", "description", "tier", "specialist",
		"rating", "reviews_count", "city", "country", "pmm_level", "hourly_rate",
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


@frappe.whitelist(allow_guest=True)
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
	return doc


@frappe.whitelist(allow_guest=True)
def list_partner_reviews(partner):
	"""Returns a partner's reviews as a plain API call, since Studio's Document List resource isn't guest-accessible."""
	return frappe.get_all(
		"Partner Review",
		filters={"partner": partner},
		fields=["reviewer_name", "rating", "headline", "quote", "reviewed_on", "verified"],
		order_by="reviewed_on desc",
		limit_page_length=100,
	)


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


@frappe.whitelist(allow_guest=True)
def get_pricing_view(partner, requirement=None):
	"""Returns pricing info for the Partner Profile Pricing tab, based on the partner's plans and the caller's saved requirement."""
	if not partner or partner == "undefined" or not frappe.db.exists("Partner", partner):
		return {"state": "loading"}

	partner_info = frappe.db.get_value("Partner", partner, ["starter_pack", "hourly_rate"], as_dict=True)
	hourly_rate = flt(partner_info.hourly_rate)
	addons = frappe.get_all("Partner Addon", filters={"parent": partner}, fields=["*"], order_by="idx")
	addon_rate = 2000 if partner_info.starter_pack else hourly_rate

	if not requirement:
		customer = _get_customer_for_user()
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


@frappe.whitelist()
def save_price_estimate(partner, selected_addons, total, requirement=None, pack_type=None):
	"""Saves a customer's price estimate (pack plus add-ons) at the moment they contact the partner about it."""
	customer = _get_customer_for_user()
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


@frappe.whitelist()
def get_my_review_for_partner(partner):
	"""Returns the caller's own review of a partner, if one exists, so the review form opens pre-filled."""
	customer = _get_customer_for_user()
	if not customer:
		return None
	rows = frappe.get_all(
		"Partner Review", filters={"partner": partner, "customer": customer}, fields=["*"], limit_page_length=1
	)
	return rows[0] if rows else None


@frappe.whitelist()
def submit_partner_review(
	partner, rating, headline=None, quote=None,
	business_understanding=None, implementation_quality=None, communication=None,
	timeliness=None, support=None, technical_expertise=None,
):
	"""Creates or updates the caller's review of a partner."""
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

	return {"name": doc.name}
