import json
import mimetypes

import frappe
from frappe import _
from frappe.utils import now_datetime

from connect.api import _get_customer_for_user
from connect.permissions import (
	_check_can_write,
	_dm_thread_pair,
	_has_full_access,
	_my_side,
	_thread_membership,
)


@frappe.whitelist()
def add_thread_member(thread, email, side, permission="Write"):
	# adding member to chat
	thread_doc = frappe.get_doc("Connect Thread", thread)
	member, created_user = thread_doc.add_member(email, side, permission, frappe.session.user)
	return {"member": member.name, "created_user": created_user}


@frappe.whitelist()
def remove_thread_member(thread, member):
	# removing member from chat
	thread_doc = frappe.get_doc("Connect Thread", thread)
	member_doc = thread_doc.remove_member(member, frappe.session.user)
	return {"removed": member_doc.user}


@frappe.whitelist()
def close_thread(thread):
	# closing the chat thread
	thread_doc = frappe.get_doc("Connect Thread", thread)
	thread_doc.close(frappe.session.user)
	return {"status": thread_doc.status}


def _format_requirement_message(customer, note=None):
	"""Turns the customer's saved Requirement into a readable message body, with an optional note appended."""
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
	"""Returns the caller's saved Requirement as a dict, to seed a draft Requirement card in a new thread."""
	user = frappe.session.user
	customer = _get_customer_for_user(user)
	if not customer:
		return None

	requirement = frappe.db.get_value("Requirement", {"customer": customer}, "name", order_by="creation desc")
	if not requirement:
		return None

	req = frappe.get_doc("Requirement", requirement)
	return {
		"company_name": req.company_name,
		"country": req.country,
		"industry": req.industry,
		"apps": [a.app for a in req.apps],
		"looking_for": req.looking_for,
		"company_size": req.company_size,
		"current_situation": req.current_situation,
		"timeline": req.timeline,
		"delivery_preference": req.delivery_preference,
		"budget": req.budget,
	}


@frappe.whitelist()
def start_partner_thread(partner, message=None):
	"""Finds or creates the (customer, partner) thread and adds both sides as members, for the Contact Partner action."""
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
def make_thread_admin(thread, member):
	"""Admin-transfer logic lives on Connect Thread Member's make_admin()."""
	member_doc = frappe.get_doc("Connect Thread Member", member)
	if member_doc.thread != thread:
		frappe.throw(_("Member does not belong to this thread"))
	member_doc.make_admin(frappe.session.user)
	return {"new_admin": member_doc.user}


@frappe.whitelist()
def get_thread_admins(thread):
	"""Returns the two companies' admin emails, to show an Admin badge and gate per-member actions."""
	user = frappe.session.user
	if not (_has_full_access(user) or _thread_membership(thread, user)):
		frappe.throw(_("You don't have access to this thread"), frappe.PermissionError)

	thread_doc = frappe.db.get_value("Connect Thread", thread, ["customer", "partner"], as_dict=True)
	if not thread_doc:
		frappe.throw(_("Thread not found"))

	partner_admin = frappe.db.get_value(
		"Connect Partner Member", {"partner": thread_doc.partner, "is_admin": 1}, "user"
	)
	customer_admin = frappe.db.get_value(
		"Customer Team Member", {"customer": thread_doc.customer, "is_admin": 1}, "user"
	)
	return {"partner_admin": partner_admin, "customer_admin": customer_admin}


@frappe.whitelist()
def get_thread_member_profiles(thread):
	"""Returns name and photo for everyone who's ever been a thread member, for the sender hover card in chat."""
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
	"""Returns the sidebar thread list with a last-message preview and unread count, scoped to what the caller can still see."""
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
	"""Clears the caller's unread badge by bumping their own last-read time; silently does nothing if their membership is stale."""
	frappe.db.set_value(
		"Connect Thread Member",
		{"thread": thread, "user": frappe.session.user, "is_removed": 0},
		"last_read_at",
		now_datetime(),
	)


def _stage_chat_attachment():
	"""Shared file-upload logic behind the thread and DM attachment endpoints."""
	uploaded = frappe.request.files.get("file") if frappe.request else None
	if not uploaded:
		frappe.throw(_("No file was uploaded"))

	filename = uploaded.filename or ""

	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": filename,
		"content": uploaded.stream.read(),
		"is_private": 1,
	})
	file_doc.insert(ignore_permissions=True)

	return {
		"file_url": file_doc.file_url,
		"file_name": filename,
		"file_type": mimetypes.guess_type(filename)[0],
		"file_size": file_doc.file_size,
	}


@frappe.whitelist()
def upload_chat_attachment(thread):
	"""Stages a file upload for the composer's preview before it's attached to a sent message."""
	_check_can_write(thread, frappe.session.user)
	return _stage_chat_attachment()


@frappe.whitelist()
def upload_dm_attachment(thread):
	"""Stages a file upload for a DM, the DM counterpart to upload_chat_attachment."""
	user = frappe.session.user
	pair = frappe.db.get_value("Connect DM Thread", thread, ["user_a", "user_b"], as_dict=True)
	if not pair or user not in (pair.user_a, pair.user_b):
		frappe.throw(_("You don't have access to this conversation"), frappe.PermissionError)
	return _stage_chat_attachment()


@frappe.whitelist()
def remove_chat_attachment(file_url):
	"""Discards a staged upload before it's attached to a message; only the uploader can do this."""
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
	"""Creates a chat message carrying text, a file, or a Requirement snapshot — one path for every message type."""
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
	"""Deletes a message for everyone; authorization and cleanup live in Connect Message's on_trash()."""
	frappe.delete_doc("Connect Message", message, ignore_permissions=True)


@frappe.whitelist()
def edit_message(message, content):
	"""Edits your own text message in place; authorization and validation live in Connect Message's validate()."""
	doc = frappe.get_doc("Connect Message", message)
	doc.content = content
	doc.save(ignore_permissions=True)
	return doc.as_dict()


@frappe.whitelist()
def pin_message(message):
	"""Resolves which thread a message belongs to; pin/unpin logic itself lives on Connect Thread."""
	doc = frappe.get_doc("Connect Message", message)
	thread_doc = frappe.get_doc("Connect Thread", doc.thread)
	thread_doc.pin(message, frappe.session.user)
	return {"thread": thread_doc.name, "pinned_message": thread_doc.pinned_message}


@frappe.whitelist()
def unpin_message(thread):
	thread_doc = frappe.get_doc("Connect Thread", thread)
	thread_doc.unpin(frappe.session.user)
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


@frappe.whitelist()
def get_my_message_templates():
	"""Returns quick-reply templates visible to the caller: shared defaults for their side plus their own personal ones."""
	return frappe.get_list(
		"Connect Message Template",
		fields=["name", "title", "content", "side", "is_global"],
		order_by="is_global desc, title asc",
	)


@frappe.whitelist()
def create_message_template(title, content):
	"""Creates a personal quick-reply template for the caller's own side."""
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
	"""Finds or creates the 1:1 DM thread with a user, storing participants in a fixed order so the pair is never duplicated."""
	me = frappe.session.user
	if user == me:
		frappe.throw(_("You can't start a conversation with yourself"))
	if not frappe.db.exists("User", user):
		frappe.throw(_("User not found"))

	user_a, user_b = sorted([me, user])

	existing = frappe.db.get_value("Connect DM Thread", {"user_a": user_a, "user_b": user_b}, "name")
	if existing:
		return existing

	doc = frappe.get_doc({"doctype": "Connect DM Thread", "user_a": user_a, "user_b": user_b})
	doc.insert(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def get_my_dm_threads():
	"""Returns the DM inbox for the sidebar, one row per person the caller has ever messaged."""
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
	"""Sends a DM text or file message, the DM counterpart to send_message."""
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


@frappe.whitelist()
def delete_dm_message(message):
	"""Deletes a DM for everyone; authorization and cleanup live in Connect DM Message's on_trash()."""
	frappe.delete_doc("Connect DM Message", message, ignore_permissions=True)


@frappe.whitelist()
def edit_dm_message(message, content):
	"""Edits your own DM in place; authorization and validation live in Connect DM Message's validate()."""
	doc = frappe.get_doc("Connect DM Message", message)
	doc.content = content
	doc.save(ignore_permissions=True)
	return doc.as_dict()


@frappe.whitelist()
def pin_dm_message(message):
	"""Resolves which thread a DM belongs to; pin/unpin logic itself lives on Connect DM Thread."""
	doc = frappe.get_doc("Connect DM Message", message)
	thread_doc = frappe.get_doc("Connect DM Thread", doc.dm_thread)
	thread_doc.pin(message, frappe.session.user)
	return {"thread": thread_doc.name, "pinned_message": thread_doc.pinned_message}


@frappe.whitelist()
def unpin_dm_message(thread):
	thread_doc = frappe.get_doc("Connect DM Thread", thread)
	thread_doc.unpin(frappe.session.user)
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
