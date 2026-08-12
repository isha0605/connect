import os

import frappe
from frappe import _
from frappe.utils import now_datetime

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


@frappe.whitelist()
def send_message(thread, content="", file_url=None, file_name=None, file_type=None, file_size=None):
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
	message.insert(ignore_permissions=True)

	if file_doc_name:
		file_doc = frappe.get_doc("File", file_doc_name)
		file_doc.attached_to_doctype = "Connect Message"
		file_doc.attached_to_name = message.name
		file_doc.save(ignore_permissions=True)

	return message.as_dict()


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
