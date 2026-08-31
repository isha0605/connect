# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from connect.notifications import notify_message_deleted, notify_message_edited
from connect.permissions import _check_can_modify_message


class ConnectMessage(Document):
	def validate(self):
		if self.message_type == "File" and not self.attachment:
			frappe.throw(_("A file message must have an attachment"))
		if not self.is_new():
			self._validate_edit()

	def _validate_edit(self):
		"""Restricts edits to your own text messages; files, images, and system messages can't be edited."""
		user = frappe.session.user
		_check_can_modify_message(self.thread, self.sender, user, _("You can only edit your own messages"))
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
			notify_message_edited(self)

	def on_trash(self):
		"""Deletes a message for everyone, restricted to the sender's own messages like other chat apps."""
		user = frappe.session.user
		_check_can_modify_message(self.thread, self.sender, user, _("You can only delete your own messages"))

		if self.attachment:
			file_name = frappe.db.get_value("File", {"file_url": self.attachment}, "name")
			if file_name:
				frappe.delete_doc("File", file_name, ignore_permissions=True)

		notify_message_deleted(self)
