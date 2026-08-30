import difflib
import json
import math
import os
import re

import frappe
from frappe import _
from frappe.utils import cint, flt, get_fullname, now_datetime, nowdate, validate_email_address

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


def _my_company_membership(user: str):
	from connect.connect.utils import _my_company_membership
	return _my_company_membership(user=user)


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


def _format_requirement_message(customer, note=None):
	"""Turns the customer's most recently saved Requirement into a readable message body,
	with an optional free-text note appended underneath. None if there's neither — the
	caller skips sending a message in that case rather than posting something empty."""
	lines = []
	requirement = frappe.db.get_value("Requirement", {"customer": customer}, "name", order_by="creation desc")
	if requirement:
		req = frappe.get_doc("Requirement", requirement)
		lines.append(_("New inquiry from {0} — here's what they're looking for:").format(req.company_name or customer))
		if req.industry:
			lines.append(_("Industry: {0}").format(req.industry))
		if req.looking_for:
			lines.append(_("Looking for: {0}").format(req.looking_for))
		apps = [a.app for a in req.apps]
		if apps:
			lines.append(_("Apps: {0}").format(", ".join(apps)))
		if req.company_size:
			lines.append(_("Company size: {0}").format(req.company_size))
		if req.timeline:
			lines.append(_("Timeline: {0}").format(req.timeline))
		if req.budget:
			lines.append(_("Budget: {0}").format(req.budget))
		if req.delivery_preference:
			lines.append(_("Delivery preference: {0}").format(req.delivery_preference))

	note = (note or "").strip()
	if note:
		if lines:
			lines.append("")
		lines.append(note)

	return "\n".join(lines) if lines else None


@frappe.whitelist()
def get_requirement_snapshot():
	from connect.customer.doctype.requirement.requirement import get_requirement_snapshot
	return get_requirement_snapshot()


@frappe.whitelist()
def start_partner_thread(partner, message=None):
	"""Contact-Partner entry point: reuses an existing (customer, partner) thread if one
	already exists — threads are continuous per pair, not per inquiry, per the messaging
	spec — otherwise creates one, seats both the caller and the partner's admin as Write
	members (a partner admin has no implicit visibility into a thread they weren't
	explicitly added to). Doesn't auto-send anything on its own for a plain "Contact
	Partner" click (message=None) — the client uses `is_new_thread` to decide whether to
	seed the composer with a reviewable Requirement draft instead (see
	get_requirement_snapshot); an explicit `message` (the pricing-estimate flows) still
	posts immediately, same as before."""
	user = frappe.session.user
	customer = _get_customer_for_user(user)
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)

	thread = frappe.db.get_value("Connect Thread", {"customer": customer, "partner": partner}, "name")
	if not thread:
		thread = frappe.get_doc({
			"doctype": "Connect Thread",
			"customer": customer,
			"partner": partner,
		}).insert(ignore_permissions=True).name

	if not frappe.db.exists("Connect Thread Member", {"thread": thread, "user": user}):
		frappe.get_doc({
			"doctype": "Connect Thread Member",
			"thread": thread,
			"user": user,
			"side": "Customer",
			"permission": "Write",
			"added_by": user,
		}).insert(ignore_permissions=True)

	partner_admin = frappe.db.get_value("Connect Partner Member", {"partner": partner, "is_admin": 1}, "user")
	if partner_admin and not frappe.db.exists("Connect Thread Member", {"thread": thread, "user": partner_admin}):
		frappe.get_doc({
			"doctype": "Connect Thread Member",
			"thread": thread,
			"user": partner_admin,
			"side": "Partner",
			"permission": "Write",
			"added_by": user,
		}).insert(ignore_permissions=True)

	is_new_thread = not frappe.db.exists("Connect Message", {"thread": thread})
	if is_new_thread and message:
		content = _format_requirement_message(customer, message)
		if content:
			send_message(thread, content=content)

	return {"thread": thread, "is_new_thread": is_new_thread}


@frappe.whitelist()
def get_my_company_members():
	from connect.connect.utils import get_my_company_members
	return get_my_company_members()


@frappe.whitelist()
def get_my_team():
	from connect.connect.utils import get_my_team
	return get_my_team()


@frappe.whitelist()
def get_my_profile():
	from connect.connect.utils import get_my_profile
	return get_my_profile()


@frappe.whitelist()
def update_my_profile(
	full_name: str,
	phone: str | None = None,
	role: str | None = None,
):
	from connect.connect.utils import update_my_profile
	return update_my_profile(full_name=full_name, phone=phone, role=role)




@frappe.whitelist()
def upload_profile_image():
	from connect.connect.utils import upload_profile_image
	return upload_profile_image()


@frappe.whitelist()
def make_thread_admin(thread, member):
	"""Promote a thread member to company admin. Unlike a plain company-scoped transfer, the
	target here is a Connect Thread Member row, not necessarily an existing Customer Team/
	Partner Member — most thread members (added via add_thread_member) never get a company
	membership row at all, so one is created for them here if missing. Customer Team Member
	is a child table of Customer (unlike the standalone Connect Partner Member), so that side
	goes through the parent doc instead of a bare insert."""
	user = frappe.session.user
	member_doc = frappe.get_doc("Connect Thread Member", member)
	if member_doc.thread != thread:
		frappe.throw(_("Member does not belong to this thread"))
	if member_doc.is_removed:
		frappe.throw(_("A removed member can't be made admin"))

	thread_doc = frappe.get_doc("Connect Thread", thread)

	if member_doc.side == "Customer":
		company = thread_doc.customer
		authorized = _is_customer_admin(company, user)
	elif member_doc.side == "Partner":
		company = thread_doc.partner
		authorized = _is_partner_admin(company, user)
	else:
		frappe.throw(_("Invalid side"))

	if not authorized:
		frappe.throw(_("Only an admin of your own side can do this"), frappe.PermissionError)

	if member_doc.side == "Customer":
		customer_doc = frappe.get_doc("Customer", company)
		found = False
		for row in customer_doc.team:
			if row.user == user:
				row.is_admin = 0
			if row.user == member_doc.user:
				row.is_admin = 1
				found = True
		if not found:
			customer_doc.append("team", {"user": member_doc.user, "is_admin": 1})
		customer_doc.save(ignore_permissions=True)
	else:
		my_row = frappe.db.get_value("Connect Partner Member", {"partner": company, "user": user}, "name")
		if my_row:
			frappe.db.set_value("Connect Partner Member", my_row, "is_admin", 0)

		target_row = frappe.db.get_value(
			"Connect Partner Member", {"partner": company, "user": member_doc.user}, "name"
		)
		if target_row:
			frappe.db.set_value("Connect Partner Member", target_row, "is_admin", 1)
		else:
			frappe.get_doc({
				"doctype": "Connect Partner Member",
				"partner": company,
				"user": member_doc.user,
				"is_admin": 1,
			}).insert(ignore_permissions=True)

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
		"Customer Team Member", {"parent": thread_doc.customer, "is_admin": 1}, "user"
	)
	return {"partner_admin": partner_admin, "customer_admin": customer_admin}


@frappe.whitelist()
def get_thread_member_profiles(thread):
	"""Full name + profile photo for the hover card shown over a sender's name/avatar in chat.
	Scoped the same way get_my_threads is — includes everyone who's ever been a member (not
	just currently-active ones), so a removed member's older messages can still resolve a name.
	Not scoped to the caller's own membership beyond "can they see this thread at all", same
	boundary as _check_can_write's read-side counterpart."""
	user = frappe.session.user
	if not (_has_full_access(user) or _thread_membership(thread, user)):
		frappe.throw(_("You don't have access to this thread"), frappe.PermissionError)

	emails = frappe.get_list("Connect Thread Member", filters={"thread": thread}, pluck="user", distinct=True)
	if not emails:
		return []
	return frappe.get_list(
		"User", filters={"name": ["in", emails]}, fields=["name", "full_name", "user_image"]
	)


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
			fields=["content", "message_type", "file_name", "creation", "sender"],
			order_by="creation desc",
			limit_page_length=1,
		)
		if last:
			m = last[0]
			if m.message_type == "File":
				preview = "📎 " + (m.file_name or _("Attachment"))
			elif m.message_type == "Requirement":
				preview = _("Requirement details")
			else:
				preview = m.content or ""
			last_message_at = m.creation
			last_message_sender = m.sender
		else:
			preview = ""
			last_message_at = t.creation
			last_message_sender = None

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
			"last_message_sender": last_message_sender,
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


def _stage_chat_attachment():
	"""Shared upload logic behind upload_chat_attachment / upload_dm_attachment — only the
	permission check differs between a company thread and a DM, so that's kept in each thin
	wrapper and everything else (validation, the actual unattached File doc) lives here once."""
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
def upload_chat_attachment(thread):
	"""Stage a pdf/docx/image for the composer's attachment preview, ahead of Send. Left
	unattached to any document until send_message claims it — that's what lets the composer
	show upload progress and a remove button before a message (and its notification) exists."""
	_check_can_write(thread, frappe.session.user)
	return _stage_chat_attachment()


@frappe.whitelist()
def upload_dm_attachment(thread):
	"""DM counterpart to upload_chat_attachment — same staging logic, but permission is just
	"are you one of the two participants" rather than a Connect Thread Member Write check."""
	user = frappe.session.user
	pair = frappe.db.get_value("Connect DM Thread", thread, ["user_a", "user_b"], as_dict=True)
	if not pair or user not in (pair.user_a, pair.user_b):
		frappe.throw(_("You don't have access to this conversation"), frappe.PermissionError)
	return _stage_chat_attachment()


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
def send_message(
	thread,
	content="",
	file_url=None,
	file_name=None,
	file_type=None,
	file_size=None,
	requirement_data=None,
):
	"""Create a chat message, optionally carrying a file staged by upload_chat_attachment, or
	a Requirement snapshot (see get_requirement_snapshot) reviewed/edited by the customer in
	the composer before sending — stored as a JSON blob in `content` since it renders as a
	structured card client-side rather than plain text. Text, file and requirement messages
	all share this one path so the composer only ever needs one Send action."""
	user = frappe.session.user
	requirement_data = frappe.parse_json(requirement_data) if isinstance(requirement_data, str) else requirement_data
	content = (content or "").strip()
	if not content and not file_url and not requirement_data:
		frappe.throw(_("Message can't be empty"))

	_check_can_write(thread, user)

	file_doc_name = None
	if file_url:
		file_doc_name = frappe.db.get_value("File", {"file_url": file_url, "owner": user}, "name")
		if not file_doc_name:
			frappe.throw(_("Attachment not found"))

	if requirement_data:
		message_type = "Requirement"
		message_content = json.dumps(requirement_data)
	elif file_url:
		message_type = "File"
		message_content = content or file_name
	else:
		message_type = "Text"
		message_content = content

	message = frappe.get_doc({
		"doctype": "Connect Message",
		"thread": thread,
		"sender": user,
		"message_type": message_type,
		"content": message_content,
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
	if not _has_full_access(user):
		membership = _thread_membership(doc.thread, user)
		if not membership or membership.is_removed:
			frappe.throw(_("You no longer have access to this thread"), frappe.PermissionError)

	if doc.attachment:
		file_name = frappe.db.get_value("File", {"file_url": doc.attachment}, "name")
		if file_name:
			frappe.delete_doc("File", file_name, ignore_permissions=True)

	notify_message_deleted(doc)
	frappe.delete_doc("Connect Message", message, ignore_permissions=True)


@frappe.whitelist()
def edit_message(message, content):
	"""Edit your own text message in place — same own-message-only rule as delete_message.
	Files/images/system rows aren't editable, and an edit is never allowed to empty a message
	out entirely (that's what delete is for)."""
	from connect.connect.notifications import notify_message_edited

	user = frappe.session.user
	doc = frappe.get_doc("Connect Message", message)
	if doc.sender != user and not _has_full_access(user):
		frappe.throw(_("You can only edit your own messages"), frappe.PermissionError)
	if not _has_full_access(user):
		membership = _thread_membership(doc.thread, user)
		if not membership or membership.is_removed:
			frappe.throw(_("You no longer have access to this thread"), frappe.PermissionError)
	if doc.message_type != "Text":
		frappe.throw(_("Only text messages can be edited"))

	content = (content or "").strip()
	if not content:
		frappe.throw(_("Message can't be empty"))

	doc.content = content
	doc.is_edited = 1
	doc.save(ignore_permissions=True)

	notify_message_edited(doc)
	return doc.as_dict()


@frappe.whitelist()
def pin_message(message):
	"""Pin a message to the top of its thread — one at a time, pinning a new one replaces
	whichever was pinned before. Available to any thread member with Write (not just the
	sender), same audience as posting."""
	from connect.connect.notifications import notify_thread_pin_changed

	user = frappe.session.user
	doc = frappe.get_doc("Connect Message", message)
	_check_can_write(doc.thread, user)

	thread_doc = frappe.get_doc("Connect Thread", doc.thread)
	thread_doc.pinned_message = doc.name
	thread_doc.save(ignore_permissions=True)

	notify_thread_pin_changed(thread_doc, doc, user)
	return {"thread": thread_doc.name, "pinned_message": thread_doc.pinned_message}


@frappe.whitelist()
def unpin_message(thread):
	from connect.connect.notifications import notify_thread_pin_changed

	user = frappe.session.user
	_check_can_write(thread, user)

	thread_doc = frappe.get_doc("Connect Thread", thread)
	thread_doc.pinned_message = None
	thread_doc.save(ignore_permissions=True)

	notify_thread_pin_changed(thread_doc, None, user)
	return {"thread": thread_doc.name, "pinned_message": None}


@frappe.whitelist()
def get_pinned_message(thread):
	user = frappe.session.user
	if not _thread_membership(thread, user) and not _has_full_access(user):
		frappe.throw(_("You don't have access to this thread"), frappe.PermissionError)

	pinned = frappe.db.get_value("Connect Thread", thread, "pinned_message")
	if not pinned:
		return None
	return frappe.db.get_value(
		"Connect Message",
		pinned,
		["name", "sender", "message_type", "content", "file_name", "creation"],
		as_dict=True,
	)


@frappe.whitelist(allow_guest=True)
def get_my_context():
	from connect.connect.utils import get_my_context
	return get_my_context()


@frappe.whitelist(allow_guest=True)
def signup_customer(
	full_name: str,
	company_name: str,
	email: str,
	password: str,
):
	from connect.customer.doctype.customer.customer import signup_customer
	return signup_customer(full_name=full_name, company_name=company_name, email=email, password=password)


def _my_side(user):
	from connect.connect.utils import _my_side
	return _my_side(user=user)


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


@frappe.whitelist()
def start_dm(user):
	"""Find-or-create the 1:1 thread with `user`. A DM has exactly two participants and no
	inherent direction, so an existing thread is found by matching the *unordered* pair —
	constraining both user_a and user_b to the 2-element {me, user} set can only ever match a
	thread between exactly those two, never a third party sharing one side."""
	me = frappe.session.user
	if user == me:
		frappe.throw(_("You can't start a conversation with yourself"))
	if not frappe.db.exists("User", user):
		frappe.throw(_("User not found"))

	existing = frappe.db.get_value(
		"Connect DM Thread", {"user_a": ["in", [me, user]], "user_b": ["in", [me, user]]}, "name"
	)
	if existing:
		return existing

	doc = frappe.get_doc({"doctype": "Connect DM Thread", "user_a": me, "user_b": user})
	doc.insert(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def get_my_dm_threads():
	"""DM inbox for the sidebar — same last-message/unread-count shape as get_my_threads, one
	row per person the caller has ever exchanged direct messages with."""
	user = frappe.session.user
	threads = frappe.get_list(
		"Connect DM Thread",
		or_filters=[["user_a", "=", user], ["user_b", "=", user]],
		fields=["name", "user_a", "user_b", "last_read_at_a", "last_read_at_b", "creation"],
		order_by="modified desc",
		limit_page_length=100,
	)

	result = []
	for t in threads:
		other = t.user_b if t.user_a == user else t.user_a
		last_read_at = t.last_read_at_a if t.user_a == user else t.last_read_at_b
		profile = frappe.db.get_value("User", other, ["full_name", "user_image"], as_dict=True) or {}

		last = frappe.get_list(
			"Connect DM Message",
			filters={"dm_thread": t.name},
			fields=["content", "message_type", "file_name", "sender", "creation"],
			order_by="creation desc",
			limit_page_length=1,
		)
		if last:
			m = last[0]
			preview = ("📎 " + (m.file_name or _("Attachment"))) if m.message_type == "File" else (m.content or "")
			last_message = preview[:140]
			last_message_at = m.creation
			last_message_sender = m.sender
		else:
			last_message = ""
			last_message_at = t.creation
			last_message_sender = None

		unread_filters = {"dm_thread": t.name, "sender": ["!=", user]}
		if last_read_at:
			unread_filters["creation"] = [">", last_read_at]
		unread_count = frappe.db.count("Connect DM Message", filters=unread_filters)

		result.append({
			"name": t.name,
			"other_user": other,
			"other_user_full_name": profile.get("full_name"),
			"other_user_image": profile.get("user_image"),
			"last_message": last_message,
			"last_message_at": last_message_at,
			"last_message_sender": last_message_sender,
			"unread_count": unread_count,
		})
	return result


@frappe.whitelist()
def mark_dm_thread_read(thread):
	"""Best-effort, mirrors mark_thread_read — a stale/foreign thread name is a silent no-op."""
	user = frappe.session.user
	pair = frappe.db.get_value("Connect DM Thread", thread, ["user_a", "user_b"], as_dict=True)
	if not pair or user not in (pair.user_a, pair.user_b):
		return
	field = "last_read_at_a" if pair.user_a == user else "last_read_at_b"
	frappe.db.set_value("Connect DM Thread", thread, field, now_datetime())


@frappe.whitelist()
def send_dm_message(thread, content="", file_url=None, file_name=None, file_type=None, file_size=None):
	"""DM counterpart to send_message — same text-or-file shape, one message per call, staged
	attachments claimed the same way (looked up by file_url + owner, then re-parented)."""
	user = frappe.session.user
	pair = frappe.db.get_value("Connect DM Thread", thread, ["user_a", "user_b"], as_dict=True)
	if not pair or user not in (pair.user_a, pair.user_b):
		frappe.throw(_("You don't have access to this conversation"), frappe.PermissionError)

	content = (content or "").strip()
	if not content and not file_url:
		frappe.throw(_("Message cannot be empty"))

	file_doc_name = None
	if file_url:
		file_doc_name = frappe.db.get_value("File", {"file_url": file_url, "owner": user}, "name")
		if not file_doc_name:
			frappe.throw(_("Attachment not found"))

	doc = frappe.get_doc({
		"doctype": "Connect DM Message",
		"dm_thread": thread,
		"sender": user,
		"message_type": "File" if file_url else "Text",
		"content": content or file_name,
	})
	if file_url:
		doc.attachment = file_url
		doc.file_name = file_name
		doc.file_type = file_type
		doc.file_size = file_size
	doc.insert(ignore_permissions=True)

	if file_doc_name:
		file_doc = frappe.get_doc("File", file_doc_name)
		file_doc.attached_to_doctype = "Connect DM Message"
		file_doc.attached_to_name = doc.name
		file_doc.save(ignore_permissions=True)

	# bumps the thread to the top of get_my_dm_threads' order_by=modified desc — a plain
	# message insert doesn't touch its parent thread's own timestamp on its own
	frappe.db.set_value("Connect DM Thread", thread, "modified", now_datetime(), update_modified=False)
	return doc.as_dict()


def _dm_thread_pair(thread, user):
	pair = frappe.db.get_value("Connect DM Thread", thread, ["user_a", "user_b"], as_dict=True)
	if not pair or user not in (pair.user_a, pair.user_b):
		frappe.throw(_("You don't have access to this conversation"), frappe.PermissionError)
	return pair


@frappe.whitelist()
def delete_dm_message(message):
	"""DM counterpart to delete_message — own-message-only, same as the company thread version
	(no admin override here since a DM has no such role)."""
	from connect.connect.notifications import notify_dm_message_deleted

	user = frappe.session.user
	doc = frappe.get_doc("Connect DM Message", message)
	_dm_thread_pair(doc.dm_thread, user)
	if doc.sender != user:
		frappe.throw(_("You can only delete your own messages"), frappe.PermissionError)

	if doc.attachment:
		file_name = frappe.db.get_value("File", {"file_url": doc.attachment}, "name")
		if file_name:
			frappe.delete_doc("File", file_name, ignore_permissions=True)

	notify_dm_message_deleted(doc)
	frappe.delete_doc("Connect DM Message", message, ignore_permissions=True)


@frappe.whitelist()
def edit_dm_message(message, content):
	"""DM counterpart to edit_message."""
	from connect.connect.notifications import notify_dm_message_edited

	user = frappe.session.user
	doc = frappe.get_doc("Connect DM Message", message)
	_dm_thread_pair(doc.dm_thread, user)
	if doc.sender != user:
		frappe.throw(_("You can only edit your own messages"), frappe.PermissionError)
	if doc.message_type != "Text":
		frappe.throw(_("Only text messages can be edited"))

	content = (content or "").strip()
	if not content:
		frappe.throw(_("Message can't be empty"))

	doc.content = content
	doc.is_edited = 1
	doc.save(ignore_permissions=True)

	notify_dm_message_edited(doc)
	return doc.as_dict()


@frappe.whitelist()
def pin_dm_message(message):
	"""DM counterpart to pin_message — either participant can pin, same as either can post."""
	from connect.connect.notifications import notify_dm_thread_pin_changed

	user = frappe.session.user
	doc = frappe.get_doc("Connect DM Message", message)
	_dm_thread_pair(doc.dm_thread, user)

	thread_doc = frappe.get_doc("Connect DM Thread", doc.dm_thread)
	thread_doc.pinned_message = doc.name
	thread_doc.save(ignore_permissions=True)

	notify_dm_thread_pin_changed(thread_doc, doc, user)
	return {"thread": thread_doc.name, "pinned_message": thread_doc.pinned_message}


@frappe.whitelist()
def unpin_dm_message(thread):
	from connect.connect.notifications import notify_dm_thread_pin_changed

	user = frappe.session.user
	_dm_thread_pair(thread, user)

	thread_doc = frappe.get_doc("Connect DM Thread", thread)
	thread_doc.pinned_message = None
	thread_doc.save(ignore_permissions=True)

	notify_dm_thread_pin_changed(thread_doc, None, user)
	return {"thread": thread_doc.name, "pinned_message": None}


@frappe.whitelist()
def get_pinned_dm_message(thread):
	user = frappe.session.user
	_dm_thread_pair(thread, user)

	pinned = frappe.db.get_value("Connect DM Thread", thread, "pinned_message")
	if not pinned:
		return None
	return frappe.db.get_value(
		"Connect DM Message",
		pinned,
		["name", "sender", "message_type", "content", "file_name", "creation"],
		as_dict=True,
	)




def _fts_rank(search_term: str, allowed_names: list[str]):
	from connect.partner.doctype.partner.partner import _fts_rank
	return _fts_rank(search_term=search_term, allowed_names=allowed_names)


def _fuzzy_rank(
	search_term: str,
	candidates: list[dict],
	threshold: float = 0.65,
):
	from connect.partner.doctype.partner.partner import _fuzzy_rank
	return _fuzzy_rank(search_term=search_term, candidates=candidates, threshold=threshold)




# Operators the CRM-style Filter component can emit (its own WIRE_OPERATOR map) —
# validated against this whitelist before reaching the query.


@frappe.whitelist(allow_guest=True)
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
	# int/float left untyped here on purpose — this is a whitelisted endpoint's outer
	# boundary, and GET query params always arrive as strings; an untouched filter
	# shows up as min_rating="" (not omitted, not None), which frappe.whitelist()'s
	# pydantic-backed type validation rejects for float/int before the function body
	# ever runs (real regression: 2026-08-29, every search_partners call 417'd).
	# The real function this delegates to keeps its own float/int hints and does its
	# own `not in (None, "")` handling — this outer copy just has to not choke first.
	min_rating=None,
	min_pmm_level=None,
	max_response_time=None,
	extra_filters: str | list | None = None,
	sort: str | None = None,
	limit=100,
):
	from connect.partner.doctype.partner.partner import search_partners
	return search_partners(search=search, industry=industry, product=product, region=region, delivery_mode=delivery_mode, country=country, tier=tier, business_process=business_process, implementation_type=implementation_type, language=language, min_rating=min_rating, min_pmm_level=min_pmm_level, max_response_time=max_response_time, extra_filters=extra_filters, sort=sort, limit=limit)


# The finder wizard's industry options don't share the same value set as
# Partner.industry (different taxonomy, written for customers rather than
# partner classification) — translate to the closest Partner industry value.


# Real, defensible mappings from the wizard's customer-facing answers to Partner
# classification data. Deliberately partial — an answer with no clean equivalent
# (company size, timeline, budget, several "looking for" / "current situation"
# values) is left unmapped rather than guessed at, so the live count only ever
# narrows on a real signal.


@frappe.whitelist(allow_guest=True)
def count_matching_partners(answers: dict | str | None = None):
	from connect.partner.doctype.partner.partner import count_matching_partners
	return count_matching_partners(answers=answers)


def _score_partners_by_requirements(answers: dict):
	from connect.partner.doctype.partner.partner import _score_partners_by_requirements
	return _score_partners_by_requirements(answers=answers)


@frappe.whitelist(allow_guest=True)
def wizard_match_state(answers: dict | str | None = None):
	from connect.partner.doctype.partner.partner import wizard_match_state
	return wizard_match_state(answers=answers)


@frappe.whitelist(allow_guest=True)
def list_matching_partners(answers: dict | str | None = None, limit=8):  # limit untyped: see search_partners
	from connect.partner.doctype.partner.partner import list_matching_partners
	return list_matching_partners(answers=answers, limit=limit)


@frappe.whitelist(allow_guest=True)
def list_partner_countries():
	from connect.partner.doctype.partner.partner import list_partner_countries
	return list_partner_countries()


@frappe.whitelist(allow_guest=True)
def list_partner_filter_options():
	from connect.partner.doctype.partner.partner import list_partner_filter_options
	return list_partner_filter_options()


def _get_customer_for_user(user: str | None = None):
	from connect.customer.doctype.customer.customer import get_customer_for_user
	return get_customer_for_user(user=user)


@frappe.whitelist(allow_guest=True)
def get_my_customer():
	from connect.customer.doctype.customer.customer import get_my_customer
	return get_my_customer()


@frappe.whitelist(allow_guest=True)
def get_my_shortlisted_partner_names():
	from connect.customer.doctype.shortlist.shortlist import get_my_shortlisted_partner_names
	return get_my_shortlisted_partner_names()


@frappe.whitelist()
def add_to_shortlist(partner: str):
	from connect.customer.doctype.shortlist.shortlist import add_to_shortlist
	return add_to_shortlist(partner=partner)


@frappe.whitelist()
def remove_from_shortlist(partner: str):
	from connect.customer.doctype.shortlist.shortlist import remove_from_shortlist
	return remove_from_shortlist(partner=partner)


@frappe.whitelist()
def list_my_shortlist():
	from connect.customer.doctype.shortlist.shortlist import list_my_shortlist
	return list_my_shortlist()


@frappe.whitelist()
def save_customer_requirement(
	company_name: str,
	country: str,
	industry: str,
	apps: str | list | None = None,
	looking_for: str | None = None,
	company_size: str | None = None,
	current_situation: str | None = None,
	timeline: str | None = None,
	delivery_preference: str | None = None,
	budget: str | None = None,
	special_requirements: str | None = None,
	additional_notes: str | None = None,
	outcome: str | None = None,
):
	from connect.customer.doctype.requirement.requirement import save_customer_requirement
	return save_customer_requirement(company_name=company_name, country=country, industry=industry, apps=apps, looking_for=looking_for, company_size=company_size, current_situation=current_situation, timeline=timeline, delivery_preference=delivery_preference, budget=budget, special_requirements=special_requirements, additional_notes=additional_notes, outcome=outcome)


@frappe.whitelist(allow_guest=True)
def get_my_requirement():
	from connect.customer.doctype.requirement.requirement import get_my_requirement
	return get_my_requirement()


@frappe.whitelist(allow_guest=True)
def get_partner_preview(partner: str):
	from connect.partner.doctype.partner.partner import get_partner_preview
	return get_partner_preview(partner=partner)


@frappe.whitelist(allow_guest=True)
def get_partner_document(partner: str):
	from connect.partner.doctype.partner.partner import get_partner_document
	return get_partner_document(partner=partner)


@frappe.whitelist(allow_guest=True)
def list_partner_reviews(partner: str):
	from connect.partner.doctype.partner_review.partner_review import list_partner_reviews
	return list_partner_reviews(partner=partner)


# Which packs are the "closest fit" for a given requirement's product interest,
# derived from Requirement.apps (there's no dedicated product_interest field —
# apps already carries this signal, since its options come from the real App
# doctype and already include "ERPNext" and "Frappe HR").
def _pack_is_primary_match(
	pack_key: str,
	has_erpnext: bool,
	has_hr: bool,
):
	from connect.partner.doctype.partner.partner import _pack_is_primary_match
	return _pack_is_primary_match(pack_key=pack_key, has_erpnext=has_erpnext, has_hr=has_hr)


@frappe.whitelist(allow_guest=True)
def get_pricing_view(partner: str, requirement: str | None = None):
	from connect.customer.doctype.price_estimate.price_estimate import get_pricing_view
	return get_pricing_view(partner=partner, requirement=requirement)


@frappe.whitelist()
def save_price_estimate(
	partner: str,
	selected_addons: str | list,
	total,  # untyped: see search_partners
	requirement: str | None = None,
	pack_type: str | None = None,
):
	from connect.customer.doctype.price_estimate.price_estimate import save_price_estimate
	return save_price_estimate(partner=partner, selected_addons=selected_addons, total=total, requirement=requirement, pack_type=pack_type)


@frappe.whitelist()
def get_my_review_for_partner(partner: str):
	from connect.partner.doctype.partner_review.partner_review import get_my_review_for_partner
	return get_my_review_for_partner(partner=partner)


@frappe.whitelist()
def submit_partner_review(
	partner: str,
	rating,  # untyped: see search_partners
	headline: str | None = None,
	quote: str | None = None,
	business_understanding=None,
	implementation_quality=None,
	communication=None,
	timeliness=None,
	support=None,
	technical_expertise=None,
):
	from connect.partner.doctype.partner_review.partner_review import submit_partner_review
	return submit_partner_review(partner=partner, rating=rating, headline=headline, quote=quote, business_understanding=business_understanding, implementation_quality=implementation_quality, communication=communication, timeliness=timeliness, support=support, technical_expertise=technical_expertise)