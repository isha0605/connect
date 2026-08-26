# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from connect.permissions import _has_full_access, _thread_membership


class ConnectMessage(Document):
	def validate(self):
		if self.message_type == "File" and not self.attachment:
			frappe.throw(_("A file message must have an attachment"))
		if not self.is_new():
			self._validate_edit()

	def _validate_edit(self):
		"""Same own-message-only rule as on_trash. Files/images/system rows aren't editable,
		and an edit is never allowed to empty a message out entirely (that's what delete is
		for)."""
		user = frappe.session.user
		if self.sender != user and not _has_full_access(user):
			frappe.throw(_("You can only edit your own messages"), frappe.PermissionError)
		if not _has_full_access(user):
			membership = _thread_membership(self.thread, user)
			if not membership or membership.is_removed:
				frappe.throw(_("You no longer have access to this thread"), frappe.PermissionError)
		if self.message_type != "Text":
			frappe.throw(_("Only text messages can be edited"))

		content = (self.content or "").strip()
		if not content:
			frappe.throw(_("Message can't be empty"))
		self.content = content
		self.is_edited = 1
		# Set only here (never during insert's own validate/before_save pass), so on_update
		# can tell an actual edit apart from any other future path that might call .save().
		self.flags._was_edited = True

	def on_update(self):
		if self.flags.get("_was_edited"):
			from connect.notifications import notify_message_edited

			notify_message_edited(self)

	def on_trash(self):
		"""Delete for everyone — restricted to the sender's own messages, same as every
		mainstream chat app: the doctype's own permission model would technically allow any
		thread member with Write to delete anyone's message (that's for moderation elsewhere),
		but "delete for everyone" specifically only ever means *your own* message."""
		from connect.notifications import notify_message_deleted

		user = frappe.session.user
		if self.sender != user and not _has_full_access(user):
			frappe.throw(_("You can only delete your own messages"), frappe.PermissionError)
		if not _has_full_access(user):
			membership = _thread_membership(self.thread, user)
			if not membership or membership.is_removed:
				frappe.throw(_("You no longer have access to this thread"), frappe.PermissionError)

		if self.attachment:
			file_name = frappe.db.get_value("File", {"file_url": self.attachment}, "name")
			if file_name:
				frappe.delete_doc("File", file_name, ignore_permissions=True)

		notify_message_deleted(self)
