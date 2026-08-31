import json

import frappe
from frappe import _

from connect.api.attachments import _attach_file_to_message, _claim_staged_attachment
from connect.permissions import _check_can_read, _check_can_write


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
):
	"""Creates a chat message carrying text, a file, or a Requirement snapshot — one path for every message type."""
	user = frappe.session.user
	requirement_data = frappe.parse_json(requirement_data) if isinstance(requirement_data, str) else requirement_data
	content = (content or "").strip()
	if not content and not file_url and not requirement_data:
		frappe.throw(_("Message can't be empty"))

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
