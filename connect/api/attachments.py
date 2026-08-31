import mimetypes

import frappe
from frappe import _

from connect.permissions import _check_can_write, _dm_thread_pair


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
	_dm_thread_pair(thread, frappe.session.user)
	return _stage_chat_attachment()


def _claim_staged_attachment(file_url, user):
	"""Resolves a staged File upload by url/owner, or throws — shared by send_message and send_dm_message."""
	file_doc_name = frappe.db.get_value("File", {"file_url": file_url, "owner": user}, "name")
	if not file_doc_name:
		frappe.throw(_("Attachment not found"))
	return file_doc_name


def _attach_file_to_message(file_doc_name, doctype, name):
	"""Re-parents a staged File onto the message it was sent with — shared by send_message and send_dm_message."""
	file_doc = frappe.get_doc("File", file_doc_name)
	file_doc.attached_to_doctype = doctype
	file_doc.attached_to_name = name
	file_doc.save()


@frappe.whitelist()
def remove_chat_attachment(file_url):
	"""Discards a staged upload before it's attached to a message; only the uploader can do this."""
	user = frappe.session.user
	file_name = frappe.db.get_value(
		"File", {"file_url": file_url, "owner": user, "attached_to_name": ["is", "not set"]}, "name"
	)
	if not file_name:
		frappe.throw(_("Attachment not found"))
	frappe.delete_doc("File", file_name)
