import difflib
import json
import math
import os
import re

import frappe
from frappe import _
from frappe.utils import cint, flt, get_fullname, now_datetime, nowdate

from connect.connect.permissions import (
	_has_full_access,
	_is_customer_admin,
	_is_partner_admin,
	_thread_membership,
)

# Only these are shareable in chat — keeps the surface small and avoids serving arbitrary
# uploads (e.g. executables, svg/html which can carry script content) back through chat.
ALLOWED_CHAT_FILE_EXTENSIONS = {
	".pdf": "application/pdf",
	".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
	".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
	".png": "image/png",
	".jpg": "image/jpeg",
	".jpeg": "image/jpeg",
	".gif": "image/gif",
	".webp": "image/webp",
}
MAX_CHAT_FILE_SIZE = 25 * 1024 * 1024  # 25 MB


def _post_system_message(thread, content):
	frappe.get_doc({
		"doctype": "Connect Message",
		"thread": thread,
		"sender": frappe.session.user,
		"message_type": "System",
		"content": content,
	}).insert(ignore_permissions=True)


def _my_company_membership(user):
	"""Returns (doctype, company, row) for whichever company this user belongs to, or
	(None, None, None) if neither. A user is assumed to belong to at most one company."""
	customer_row = frappe.db.get_value(
		"Connect Customer Member", {"user": user}, ["name", "customer", "is_admin"], as_dict=True
	)
	if customer_row:
		return "Connect Customer Member", customer_row.customer, customer_row
	partner_row = frappe.db.get_value(
		"Connect Partner Member", {"user": user}, ["name", "partner", "is_admin"], as_dict=True
	)
	if partner_row:
		return "Connect Partner Member", partner_row.partner, partner_row
	return None, None, None


@frappe.whitelist()
def add_thread_member(thread, email, side, permission="Write"):
	"""Add someone to a thread, creating their User account first if it doesn't exist yet.
	A regular portal admin has no create-permission on User, so this has to happen here,
	server-side, after independently re-checking the caller is really an admin of the
	side they're claiming to add to — never trust the client's own claim of authority."""
	email = email.strip().lower()
	user = frappe.session.user

	thread_doc = frappe.db.get_value("Connect Thread", thread, ["customer", "partner"], as_dict=True)
	if not thread_doc:
		frappe.throw(_("Thread not found"))

	if side == "Customer":
		authorized = _is_customer_admin(thread_doc.customer, user)
	elif side == "Partner":
		authorized = _is_partner_admin(thread_doc.partner, user)
	else:
		frappe.throw(_("Invalid side"))

	if not authorized:
		frappe.throw(_("Only an admin of your own side can add members"), frappe.PermissionError)

	created_user = False
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"user_type": "Website User",
			"send_welcome_email": 0,
		}).insert(ignore_permissions=True)
		created_user = True

	member = frappe.get_doc({
		"doctype": "Connect Thread Member",
		"thread": thread,
		"user": email,
		"side": side,
		"permission": permission,
		"added_by": user,
	})
	member.insert(ignore_permissions=True)

	_post_system_message(thread, _("{0} was added to this thread").format(email))

	return {"member": member.name, "created_user": created_user}


@frappe.whitelist()
def remove_thread_member(thread, member):
	"""Soft-remove a member from a thread. Only an admin of that member's own side may
	remove them — mirrors add_thread_member's authorization model."""
	user = frappe.session.user
	member_doc = frappe.get_doc("Connect Thread Member", member)
	if member_doc.thread != thread:
		frappe.throw(_("Member does not belong to this thread"))

	thread_doc = frappe.db.get_value("Connect Thread", thread, ["customer", "partner"], as_dict=True)
	if not thread_doc:
		frappe.throw(_("Thread not found"))

	if member_doc.side == "Customer":
		authorized = _is_customer_admin(thread_doc.customer, user)
	elif member_doc.side == "Partner":
		authorized = _is_partner_admin(thread_doc.partner, user)
	else:
		frappe.throw(_("Invalid side"))

	if not authorized:
		frappe.throw(_("Only an admin of your own side can remove members"), frappe.PermissionError)

	member_doc.is_removed = 1
	member_doc.save(ignore_permissions=True)

	_post_system_message(thread, _("{0} was removed from this thread").format(member_doc.user))

	return {"removed": member_doc.user}


@frappe.whitelist()
def close_thread(thread):
	"""Partner-admin-only, per spec — customer side has no close action."""
	user = frappe.session.user
	thread_doc = frappe.get_doc("Connect Thread", thread)

	if not _is_partner_admin(thread_doc.partner, user):
		frappe.throw(_("Only the partner admin can close this thread"), frappe.PermissionError)

	if thread_doc.status == "Closed":
		frappe.throw(_("Thread is already closed"))

	thread_doc.status = "Closed"
	thread_doc.closed_by = user
	thread_doc.closed_on = now_datetime()
	thread_doc.save(ignore_permissions=True)

	_post_system_message(thread, _("Thread closed by {0}").format(user))

	return {"status": thread_doc.status}


@frappe.whitelist()
def get_my_company_members():
	"""The caller's own company roster (Customer Member or Partner Member rows) — used to
	populate the 'transfer admin to' picker. Not thread-scoped, unlike everything else here."""
	user = frappe.session.user
	doctype, company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	fieldname = "customer" if doctype == "Connect Customer Member" else "partner"
	return frappe.get_all(doctype, filters={fieldname: company}, fields=["user", "is_admin"])


@frappe.whitelist()
def make_thread_admin(thread, member):
	"""Promote a thread member to company admin. Unlike a plain company-scoped transfer, the
	target here is a Connect Thread Member row, not necessarily an existing Connect Customer/
	Partner Member — most thread members (added via add_thread_member) never get a company
	membership row at all, so one is created for them here if missing."""
	user = frappe.session.user
	member_doc = frappe.get_doc("Connect Thread Member", member)
	if member_doc.thread != thread:
		frappe.throw(_("Member does not belong to this thread"))

	thread_doc = frappe.get_doc("Connect Thread", thread)

	if member_doc.side == "Customer":
		company_doctype, member_doctype, company, fieldname = (
			"Connect Customer", "Connect Customer Member", thread_doc.customer, "customer",
		)
		authorized = _is_customer_admin(company, user)
	elif member_doc.side == "Partner":
		company_doctype, member_doctype, company, fieldname = (
			"Connect Partner", "Connect Partner Member", thread_doc.partner, "partner",
		)
		authorized = _is_partner_admin(company, user)
	else:
		frappe.throw(_("Invalid side"))

	if not authorized:
		frappe.throw(_("Only an admin of your own side can do this"), frappe.PermissionError)

	my_row = frappe.db.get_value(member_doctype, {fieldname: company, "user": user}, "name")
	if my_row:
		frappe.db.set_value(member_doctype, my_row, "is_admin", 0)

	target_row = frappe.db.get_value(member_doctype, {fieldname: company, "user": member_doc.user}, "name")
	if target_row:
		frappe.db.set_value(member_doctype, target_row, "is_admin", 1)
	else:
		frappe.get_doc({
			"doctype": member_doctype,
			fieldname: company,
			"user": member_doc.user,
			"is_admin": 1,
		}).insert(ignore_permissions=True)

	frappe.db.set_value(company_doctype, company, "admin_user", member_doc.user)

	return {"new_admin": member_doc.user}


@frappe.whitelist()
def get_thread_admins(thread):
	"""Admin emails for the two companies on this thread — used to show an Admin badge
	next to the right member and to gate the per-member actions menu."""
	thread_doc = frappe.db.get_value("Connect Thread", thread, ["customer", "partner"], as_dict=True)
	if not thread_doc:
		frappe.throw(_("Thread not found"))

	partner_admin = frappe.db.get_value(
		"Connect Partner Member", {"partner": thread_doc.partner, "is_admin": 1}, "user"
	)
	customer_admin = frappe.db.get_value(
		"Connect Customer Member", {"customer": thread_doc.customer, "is_admin": 1}, "user"
	)
	return {"partner_admin": partner_admin, "customer_admin": customer_admin}


@frappe.whitelist()
def get_my_threads():
	"""Thread list for the sidebar, enriched with what a plain 'Connect Thread' list can't
	give the client: a last-message preview and an unread count. Both are scoped to the
	requesting member's own view of the thread — a member removed part-way through only ever
	sees (and counts) messages up to their removal, mirroring has_message_permission's frozen
	view instead of quietly leaking anything posted after they left."""
	user = frappe.session.user
	threads = frappe.get_list(
		"Connect Thread",
		fields=["name", "customer", "partner", "status", "creation"],
		order_by="modified desc",
		limit_page_length=100,
	)

	result = []
	for t in threads:
		membership = frappe.db.get_value(
			"Connect Thread Member",
			{"thread": t.name, "user": user},
			["last_read_at", "is_removed", "removed_on"],
			as_dict=True,
		) or {}

		message_filters = [["thread", "=", t.name]]
		if membership.get("is_removed") and membership.get("removed_on"):
			message_filters.append(["creation", "<=", membership["removed_on"]])

		last = frappe.get_list(
			"Connect Message",
			filters=message_filters,
			fields=["content", "message_type", "file_name", "creation"],
			order_by="creation desc",
			limit_page_length=1,
		)
		if last:
			m = last[0]
			preview = ("📎 " + (m.file_name or _("Attachment"))) if m.message_type == "File" else (m.content or "")
			last_message_at = m.creation
		else:
			preview = ""
			last_message_at = t.creation

		unread_filters = message_filters + [["sender", "!=", user]]
		if membership.get("last_read_at"):
			unread_filters.append(["creation", ">", membership["last_read_at"]])
		unread_count = frappe.db.count("Connect Message", filters=unread_filters)

		result.append({
			"name": t.name,
			"customer": t.customer,
			"partner": t.partner,
			"status": t.status,
			"creation": t.creation,
			"last_message": preview[:140],
			"last_message_at": last_message_at,
			"unread_count": unread_count,
		})

	return result


@frappe.whitelist()
def mark_thread_read(thread):
	"""Clears the unread badge for the caller by bumping their own last_read_at — best-effort,
	so a stale/removed membership is a silent no-op rather than an error the composer has to
	handle."""
	frappe.db.set_value(
		"Connect Thread Member",
		{"thread": thread, "user": frappe.session.user, "is_removed": 0},
		"last_read_at",
		now_datetime(),
	)


def _check_can_write(thread, user):
	if _has_full_access(user):
		return
	membership = _thread_membership(thread, user)
	if not membership or membership.is_removed or membership.permission != "Write":
		frappe.throw(_("You don't have permission to post in this thread"), frappe.PermissionError)
	if frappe.db.get_value("Connect Thread", thread, "status") == "Closed":
		frappe.throw(_("This thread is closed"))


@frappe.whitelist()
def upload_chat_attachment(thread):
	"""Stage a pdf/docx/image for the composer's attachment preview, ahead of Send. Left
	unattached to any document until send_message claims it — that's what lets the composer
	show upload progress and a remove button before a message (and its notification) exists."""
	user = frappe.session.user
	_check_can_write(thread, user)

	uploaded = frappe.request.files.get("file") if frappe.request else None
	if not uploaded:
		frappe.throw(_("No file was uploaded"))

	filename = uploaded.filename or ""
	ext = os.path.splitext(filename)[1].lower()
	if ext not in ALLOWED_CHAT_FILE_EXTENSIONS:
		frappe.throw(_("Only PDF, DOCX, and image files can be shared in chat"))

	content = uploaded.stream.read()
	if len(content) > MAX_CHAT_FILE_SIZE:
		frappe.throw(
			_("File is too large — the limit is {0} MB").format(MAX_CHAT_FILE_SIZE // (1024 * 1024))
		)

	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": filename,
		"content": content,
		"is_private": 1,
	})
	file_doc.insert(ignore_permissions=True)

	return {
		"file_url": file_doc.file_url,
		"file_name": filename,
		"file_type": ALLOWED_CHAT_FILE_EXTENSIONS[ext],
		"file_size": file_doc.file_size,
	}


@frappe.whitelist()
def remove_chat_attachment(file_url):
	"""Discard a staged upload before it's ever attached to a message — only the uploader can
	do this, and only while the file is still unclaimed by send_message."""
	user = frappe.session.user
	file_name = frappe.db.get_value(
		"File", {"file_url": file_url, "owner": user, "attached_to_name": ["is", "not set"]}, "name"
	)
	if not file_name:
		frappe.throw(_("Attachment not found"))
	frappe.delete_doc("File", file_name, ignore_permissions=True)


def _resolve_private_recipients(thread, user, recipients):
	"""Validate and normalize a private message's addressee list: must resolve to at least one
	other *current* (non-removed) member of this thread. The client derives `recipients` from
	@mentions in the draft, but that's just UX — re-validated here since the client's mention
	list is never trusted for who actually gets to read the message."""
	recipients = frappe.parse_json(recipients) if isinstance(recipients, str) else (recipients or [])
	candidates = {r for r in recipients if r and r != user}
	if not candidates:
		frappe.throw(_("Mention at least one other person in the thread to send a private message"))

	valid = set(
		frappe.get_all(
			"Connect Thread Member",
			filters={"thread": thread, "user": ["in", list(candidates)], "is_removed": 0},
			pluck="user",
		)
	)
	if not valid:
		frappe.throw(_("Mention at least one other person in the thread to send a private message"))
	return valid


@frappe.whitelist()
def send_message(
	thread,
	content="",
	file_url=None,
	file_name=None,
	file_type=None,
	file_size=None,
	is_private=False,
	recipients=None,
):
	"""Create a chat message, optionally carrying a file staged by upload_chat_attachment.
	Text and file messages share this one path so the composer only ever needs one Send
	action regardless of whether an attachment is riding along."""
	user = frappe.session.user
	content = (content or "").strip()
	if not content and not file_url:
		frappe.throw(_("Message can't be empty"))

	_check_can_write(thread, user)

	file_doc_name = None
	if file_url:
		file_doc_name = frappe.db.get_value("File", {"file_url": file_url, "owner": user}, "name")
		if not file_doc_name:
			frappe.throw(_("Attachment not found"))

	message = frappe.get_doc({
		"doctype": "Connect Message",
		"thread": thread,
		"sender": user,
		"message_type": "File" if file_url else "Text",
		"content": content or file_name,
	})
	if file_url:
		message.attachment = file_url
		message.file_name = file_name
		message.file_type = file_type
		message.file_size = file_size
	if frappe.parse_json(is_private) if isinstance(is_private, str) else is_private:
		valid_recipients = _resolve_private_recipients(thread, user, recipients)
		message.is_private = 1
		message.private_to = "," + ",".join(valid_recipients) + ","
	message.insert(ignore_permissions=True)

	if file_doc_name:
		file_doc = frappe.get_doc("File", file_doc_name)
		file_doc.attached_to_doctype = "Connect Message"
		file_doc.attached_to_name = message.name
		file_doc.save(ignore_permissions=True)

	return message.as_dict()


@frappe.whitelist()
def delete_message(message):
	"""Delete a message for everyone — restricted to the sender's own messages, same as every
	mainstream chat app: the doctype's own permission model would technically allow any
	thread member with Write to delete anyone's message (that's for moderation elsewhere),
	but "delete for everyone" specifically only ever means *your own* message."""
	from connect.connect.notifications import notify_message_deleted

	user = frappe.session.user
	doc = frappe.get_doc("Connect Message", message)
	if doc.sender != user and not _has_full_access(user):
		frappe.throw(_("You can only delete your own messages"), frappe.PermissionError)

	if doc.attachment:
		file_name = frappe.db.get_value("File", {"file_url": doc.attachment}, "name")
		if file_name:
			frappe.delete_doc("File", file_name, ignore_permissions=True)

	notify_message_deleted(doc)
	frappe.delete_doc("Connect Message", message, ignore_permissions=True)


@frappe.whitelist()
def get_my_context():
	user = frappe.session.user
	customer_membership = frappe.db.get_value(
		"Connect Customer Member", {"user": user}, ["customer", "is_admin"], as_dict=True
	)
	partner_membership = frappe.db.get_value(
		"Connect Partner Member", {"user": user}, ["partner", "is_admin"], as_dict=True
	)
	return {
		"user": user,
		"customer": customer_membership,
		"partner": partner_membership,
	}


def _my_side(user):
	"""Which side (Customer/Partner) this user belongs to, or None if neither."""
	doctype, _company, _row = _my_company_membership(user)
	if doctype == "Connect Customer Member":
		return "Customer"
	if doctype == "Connect Partner Member":
		return "Partner"
	return None


@frappe.whitelist()
def get_my_message_templates():
	"""Quick-reply templates visible to the caller: global defaults for their own side, plus
	their own personal ones. No extra filtering needed here — that scoping is exactly what
	get_message_template_permission_query_conditions already enforces, via get_list (unlike
	get_all, which explicitly skips permission checks)."""
	return frappe.get_list(
		"Connect Message Template",
		fields=["name", "title", "content", "side", "is_global"],
		order_by="is_global desc, title asc",
	)


@frappe.whitelist()
def create_message_template(title, content):
	"""Create a personal (non-global) template for the caller's own side. Global templates are
	managed by platform admins directly (e.g. via Desk), not through this endpoint."""
	side = _my_side(frappe.session.user)
	if not side:
		frappe.throw(_("You are not a member of any company"))

	doc = frappe.get_doc({
		"doctype": "Connect Message Template",
		"title": title,
		"content": content,
		"side": side,
		"is_global": 0,
	})
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def update_message_template(name, title=None, content=None):
	"""Owner-only, personal templates only — has_message_template_permission enforces both."""
	doc = frappe.get_doc("Connect Message Template", name)
	if doc.is_global:
		frappe.throw(_("Global templates can't be edited here"), frappe.PermissionError)

	if title is not None:
		doc.title = title
	if content is not None:
		doc.content = content
	doc.save()
	return doc.as_dict()


@frappe.whitelist()
def delete_message_template(name):
	"""Owner-only, personal templates only — has_message_template_permission enforces both."""
	doc = frappe.get_doc("Connect Message Template", name)
	if doc.is_global:
		frappe.throw(_("Global templates can't be deleted here"), frappe.PermissionError)

	doc.delete()
	return {"deleted": name}


PARTNER_FIELDS = [
	"name", "partner_name", "logo", "tagline", "tier", "specialist",
	"rating", "reviews_count", "industry", "country", "city", "rollouts", "hourly_rate",
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

	wanted_apps = answers.get("apps") or []
	if wanted_apps:
		pool = _apply_matcher(pool, lambda p, w=wanted_apps: any(a in p["apps"] for a in w))

	for req in (answers.get("requirements") or []):
		pool = _apply_matcher(pool, REQUIREMENT_MATCHERS.get(req))

	# Proportional quality trim: every answered question should visibly move
	# the count, even ones above with no real matcher for this particular value.
	# company_name/country are excluded here -- they have no matching signal at
	# all, so counting them would trim the pool for no real reason.
	answered = sum(
		1 for k in ("looking_for", "industry", "company_size", "current_situation", "timeline", "delivery_preference", "budget")
		if answers.get(k)
	)
	if answers.get("requirements"):
		answered += 1
	if wanted_apps:
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
	customer-recognizable requirements they fail (currently: industry, apps,
	delivery mode) — not a hard AND filter. Full matches (0 missed) come first;
	partners missing 1-2 requirements are included after with `missing_label`
	naming exactly what they're short on, so a strong-but-imperfect match
	doesn't just disappear. Partners missing 3+ are excluded as too far off to
	be useful."""
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

	apps_by_partner, apps_preview_by_partner = {}, {}
	for row in frappe.get_all(
		"Partner App", filters={"parent": ["in", names]}, fields=["parent", "app"], order_by="idx asc",
	):
		apps_by_partner.setdefault(row.parent, []).append(row.app)
		preview = apps_preview_by_partner.setdefault(row.parent, [])
		if len(preview) < 2:
			preview.append(row.app)

	industry = answers.get("industry")
	wanted_industry = WIZARD_TO_PARTNER_INDUSTRY.get(industry, industry) if industry else None

	delivery = answers.get("delivery_preference")
	wanted_mode = DELIVERY_TO_MODE.get(delivery) if delivery and delivery != "No preference" else None

	wanted_apps = answers.get("apps") or []

	scored = []
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
		if len(missing) <= 2:
			scored.append((len(missing), -(row.rating or 0), name, missing))

	scored.sort(key=lambda s: (s[0], s[1]))
	scored = scored[:limit]

	result = []
	for _missing_count, _neg_rating, name, missing in scored:
		row = dict(by_name[name])
		row["apps_preview"] = apps_preview_by_partner.get(name, [])
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
	Implementation Type / Language dropdowns, plus the finder wizard's Apps
	question. Studio's "Document List" resource type calls frappe.client.get_list
	under the hood, which isn't guest-whitelisted regardless of the target
	doctype's own Guest permission — so those dropdowns silently returned
	nothing for guest visitors. This is a small API Resource instead, same fix
	as list_partner_countries above."""
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
	company_name, country, industry, apps=None,
	looking_for=None, company_size=None, current_situation=None, timeline=None, delivery_preference=None, budget=None,
	special_requirements=None, outcome=None,
):
	"""Create or update the current user's company's one Requirement — company_name/
	country/industry/apps are the 4 primary questions; everything else comes from
	the bundled, optional "Additional Requirements" step. Upserts by customer, so
	both the Find My Match wizard and the Settings "Edit Requirements" form share
	a single canonical requirement that either flow can fill in or update."""
	customer = _get_customer_for_user()
	if not customer:
		frappe.throw("Your account isn't linked to a customer company yet.", frappe.PermissionError)

	if isinstance(apps, str):
		apps = json.loads(apps or "[]")

	values = {
		"customer": customer,
		"company_name": company_name,
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

	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist(allow_guest=True)
def get_my_requirement():
	"""The current user's company's saved requirement, for prefilling the Settings
	"Edit Requirements" form — None if they haven't saved one yet (add mode), and
	for a logged-out visitor (same as no customer link)."""
	customer = _get_customer_for_user()
	if not customer:
		return None
	name = frappe.db.get_value("Requirement", {"customer": customer}, "name", order_by="creation desc")
	if not name:
		return None
	doc = frappe.get_doc("Requirement", name)
	return {
		"name": doc.name,
		"company_name": doc.company_name,
		"country": doc.country,
		"industry": doc.industry,
		"apps": [a.app for a in doc.apps],
		"looking_for": doc.looking_for,
		"company_size": doc.company_size,
		"current_situation": doc.current_situation,
		"timeline": doc.timeline,
		"delivery_preference": doc.delivery_preference,
		"budget": doc.budget,
		"special_requirements": doc.special_requirements,
	}


@frappe.whitelist(allow_guest=True)
def get_partner_preview(partner):
	"""Lightweight partner snapshot for the Find Partners list view's quick-preview
	side drawer — just enough to decide whether to open the full profile. Fetched
	on demand per click rather than bloating every row of search_partners."""
	fields = [
		"name", "partner_name", "logo", "description", "tier", "specialist",
		"rating", "reviews_count", "city", "country", "pmm_level", "hourly_rate",
		"certs_erpnext", "certs_frappe_framework", "industry", "address",
	]
	doc = frappe.db.get_value("Partner", partner, fields, as_dict=True)
	if not doc:
		frappe.throw(_("Partner not found"), frappe.DoesNotExistError)

	doc["apps"] = frappe.get_all("Partner App", filters={"parent": partner}, pluck="app", order_by="idx asc")
	doc["migrations"] = frappe.get_all(
		"Partner Migration Path", filters={"parent": partner}, pluck="migration_path", order_by="idx asc"
	)
	return doc


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
	"""Drives the Partner Profile Pricing tab. Guest-safe like the rest of the
	profile page — a logged-out visitor or one with no saved Requirement simply
	lands on "no_requirement", same honest fallback either way.

	Every partner gets an hourly-rate add-on breakdown regardless of whether they
	offer starter packs — `addon_rate` is the fixed ₹2,000/hr pack-derived rate
	for starter-pack partners (has to match their own pack price-per-hour
	exactly), or the partner's own disclosed/estimated hourly_rate otherwise.
	Packaged pricing (`state: "eligible"`) additionally requires starter_pack AND
	a requirement that wants ERPNext or Frappe HR.

	`requirement` is optional and normally left unset: the caller's own most
	recent Requirement (via Customer Team Member) is resolved automatically, so
	the frontend doesn't need to track a requirement id of its own. Passing one
	explicitly overrides that lookup.
	"""
	partner_doc = frappe.get_doc("Partner", partner)
	addons = [a.as_dict() for a in partner_doc.addons]
	addon_rate = 2000 if partner_doc.starter_pack else flt(partner_doc.hourly_rate)

	if not requirement:
		customer = _get_customer_for_user()
		if customer:
			requirement = frappe.db.get_value(
				"Requirement", {"customer": customer}, "name", order_by="creation desc"
			)

	if not partner_doc.starter_pack:
		return {
			"state": "hourly_only", "rate": partner_doc.hourly_rate,
			"addons": addons, "addon_rate": addon_rate, "requirement": requirement,
		}

	if not requirement:
		return {"state": "no_requirement", "rate": partner_doc.hourly_rate, "addons": addons, "addon_rate": addon_rate}

	req = frappe.get_doc("Requirement", requirement)
	req_apps = [a.app for a in req.apps]
	has_erpnext = "ERPNext" in req_apps
	has_hr = "Frappe HR" in req_apps

	if not (has_erpnext or has_hr):
		return {
			"state": "mismatch",
			"rate": partner_doc.hourly_rate,
			"requested_product": ", ".join(req_apps) if req_apps else None,
			"requirement": req.name,
			"addons": addons,
			"addon_rate": addon_rate,
		}

	packs = [p.as_dict() for p in partner_doc.packs]
	for p in packs:
		p["is_primary_match"] = _pack_is_primary_match(p["pack_key"], has_erpnext, has_hr)

	return {
		"state": "eligible",
		"packs": packs,
		"addons": addons,
		"requirement": req.name,
	}


@frappe.whitelist()
def save_price_estimate(partner, selected_addons, total, requirement=None, pack_type=None):
	"""Record a customer's starter-pack estimate (pack + selected add-ons) at the
	moment they choose to contact the partner about it, so the partner sees
	exactly what was being estimated rather than a blind inquiry. requirement/
	pack_type are optional — the no_requirement and mismatch pricing states have
	no eligible pack, only an hourly-rate add-on estimate, so base_price is 0 and
	pack_type stays blank for those."""
	customer = _get_customer_for_user()
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)

	if isinstance(selected_addons, str):
		selected_addons = json.loads(selected_addons or "[]")

	partner_doc = frappe.get_doc("Partner", partner)
	base_price = next((p.price for p in partner_doc.packs if p.pack_name == pack_type), 0)

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
	frappe.db.commit()
	return doc.name


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
