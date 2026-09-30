import mimetypes

import frappe
from frappe import _

from connect.permissions import _check_can_write, _dm_thread_pair


def _stage_chat_attachment():
	"""Stages an upload as an unattached File so the composer can preview it before the message is actually sent."""
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
	"""Stages a chat file upload after checking thread write access, so uploads can't be used to probe forbidden threads."""
	_check_can_write(thread, frappe.session.user)
	return _stage_chat_attachment()


@frappe.whitelist()
def upload_dm_attachment(thread):
	"""Stages a DM file upload after checking pair membership, mirroring upload_chat_attachment."""
	_dm_thread_pair(thread, frappe.session.user)
	return _stage_chat_attachment()


def _claim_staged_attachment(file_url, user):
	"""Verifies the caller uploaded this staged file, so nobody can attach someone else's upload to their message."""
	file_doc_name = frappe.db.get_value("File", {"file_url": file_url, "owner": user}, "name")
	if not file_doc_name:
		frappe.throw(_("Attachment not found"))
	return file_doc_name


def _attach_file_to_message(file_doc_name, doctype, name):
	"""Re-parents a staged File to its message so lifecycle hooks (like on_trash cleanup) work on it."""
	file_doc = frappe.get_doc("File", file_doc_name)
	file_doc.attached_to_doctype = doctype
	file_doc.attached_to_name = name
	file_doc.save()


def _copy_message_attachment(file_url):
	"""Duplicates the File so a forwarded copy survives when the original message is later deleted."""
	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		frappe.throw(_("The original file is no longer available"))
	source = frappe.get_doc("File", file_name)
	copy = frappe.get_doc({
		"doctype": "File",
		"file_name": source.file_name,
		"content": source.get_content(),
		"is_private": 1,
	})
	copy.insert(ignore_permissions=True)
	return copy


@frappe.whitelist()
def remove_chat_attachment(file_url):
	"""Discards a staged upload the uploader hasn't sent yet, so cancelling a compose doesn't leave orphan files."""
	user = frappe.session.user
	file_name = frappe.db.get_value(
		"File", {"file_url": file_url, "owner": user, "attached_to_name": ["is", "not set"]}, "name"
	)
	if not file_name:
		frappe.throw(_("Attachment not found"))
	frappe.delete_doc("File", file_name)
