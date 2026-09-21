import json

import frappe

from connect.api.attachments import _attach_file_to_message, _claim_staged_attachment, _copy_message_attachment
from connect.permissions import (
	_check_can_read,
	_check_can_write,
	_dm_thread_pair,
	_has_full_access,
)

# Requirement cards and booking cards are one-off snapshots tied to their thread, so only plain
# text and files can be forwarded.
FORWARDABLE_MESSAGE_TYPES = ("Text", "File")


def _get_message_preview(doctype, name):
	"""Shared field set for a pinned-message preview — used by get_pinned_message and get_pinned_dm_message."""
	return frappe.db.get_value(
		doctype,
		name,
		["name", "sender", "message_type", "content", "file_name", "creation"],
		as_dict=True,
	)


@frappe.whitelist()
def send_message(
	thread,
	content="",
	file_url=None,
	file_name=None,
	file_type=None,
	file_size=None,
	requirement_data=None,
	reply_to=None,
):
	"""Creates a chat message carrying text, a file, or a Requirement snapshot — one path for every message type."""
	user = frappe.session.user
	requirement_data = frappe.parse_json(requirement_data) if isinstance(requirement_data, str) else requirement_data
	content = (content or "").strip()

	_check_can_write(thread, user)

	file_doc_name = _claim_staged_attachment(file_url, user) if file_url else None

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
		# Only a reply to a message already in this same thread is meaningful — a stray/cross-thread
		# reply_to would show a quote the recipient has no way to see.
		"reply_to": reply_to if reply_to and frappe.db.exists("Connect Message", {"name": reply_to, "thread": thread}) else None,
	})
	if file_url:
		message.attachment = file_url
		message.file_name = file_name
		message.file_type = file_type
		message.file_size = file_size
	message.insert()

	if file_doc_name:
		_attach_file_to_message(file_doc_name, "Connect Message", message.name)

	return message.as_dict()


@frappe.whitelist()
def delete_message(message):
	"""Deletes a message for everyone; authorization and cleanup live in has_message_permission and Connect Message's on_trash()."""
	frappe.delete_doc("Connect Message", message)


@frappe.whitelist()
def edit_message(message, content):
	"""Edits your own text message in place; authorization and validation live in has_message_permission and Connect Message's validate()."""
	doc = frappe.get_doc("Connect Message", message)
	doc.content = content
	doc.save()
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
	_check_can_read(thread, frappe.session.user)

	pinned = frappe.db.get_value("Connect Thread", thread, "pinned_message")
	if not pinned:
		return None
	return _get_message_preview("Connect Message", pinned)


@frappe.whitelist()
def get_forward_targets():
	"""Lists the conversations the caller can forward a message into right now: threads where they have
	Write access and that aren't closed, plus every DM of theirs. Display data (names, avatars) is left to
	the client, which already has it from get_my_threads / get_my_dm_threads."""
	user = frappe.session.user

	thread_filters = {"status": ["!=", "Closed"]}
	if not _has_full_access(user):
		writable = frappe.get_all(
			"Connect Thread Member",
			filters={"user": user, "permission": "Write", "is_removed": 0},
			pluck="thread",
		)
		if not writable:
			thread_filters = None
		else:
			thread_filters["name"] = ["in", writable]
	threads = frappe.get_list("Connect Thread", filters=thread_filters, pluck="name") if thread_filters else []

	dm_threads = frappe.get_list(
		"Connect DM Thread", or_filters=[["user_a", "=", user], ["user_b", "=", user]], pluck="name"
	)

	return {"company": threads, "dm": dm_threads}


@frappe.whitelist()
def forward_message(message, source_is_dm, target_thread, target_is_dm):
	"""Sends a copy of a text or file message into another conversation as the caller, flagged as forwarded.
	Reading the original is checked by Frappe's permission system; posting to the target goes through the
	same write checks as send_message / send_dm_message."""
	user = frappe.session.user
	source_is_dm = frappe.utils.cint(source_is_dm)
	target_is_dm = frappe.utils.cint(target_is_dm)

	source = frappe.get_doc("Connect DM Message" if source_is_dm else "Connect Message", message)
	source.check_permission("read")
	if source.message_type not in FORWARDABLE_MESSAGE_TYPES:
		frappe.throw(frappe._("Only text and file messages can be forwarded"))

	source_thread = source.dm_thread if source_is_dm else source.thread
	if source_thread == target_thread and source_is_dm == target_is_dm:
		frappe.throw(frappe._("You can't forward a message into the conversation it's already in"))

	if target_is_dm:
		_dm_thread_pair(target_thread, user)
	else:
		_check_can_write(target_thread, user)

	values = {
		"doctype": "Connect DM Message" if target_is_dm else "Connect Message",
		"dm_thread" if target_is_dm else "thread": target_thread,
		"sender": user,
		"message_type": source.message_type,
		"content": source.content,
		"is_forwarded": 1,
	}
	file_copy = _copy_message_attachment(source.attachment) if source.attachment else None
	if file_copy:
		values.update(
			attachment=file_copy.file_url,
			file_name=source.file_name,
			file_type=source.file_type,
			file_size=source.file_size,
		)
	forwarded = frappe.get_doc(values)
	forwarded.insert()

	if file_copy:
		_attach_file_to_message(file_copy.name, forwarded.doctype, forwarded.name)

	return forwarded.as_dict()
