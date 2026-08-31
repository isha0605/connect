
import frappe
from frappe import _
from frappe.model.document import Document

from connect.notifications import (
	notify_dm_message_deleted,
	notify_dm_message_edited,
	resync_dm_thread_last_message_on_edit,
	resync_dm_thread_last_message_on_trash,
)


class ConnectDMMessage(Document):
	def validate(self):
		if self.message_type == "File" and not self.attachment:
			frappe.throw(_("A file message must have an attachment"))
		if not self.is_new():
			self._validate_edit()

	def _validate_edit(self):
		"""Restricts edits to text messages; ownership itself is enforced by has_dm_message_permission."""
		if self.message_type != "Text":
			frappe.throw(_("Only text messages can be edited"))

		content = (self.content or "").strip()
		if not content:
			frappe.throw(_("Message can't be empty"))
		self.content = content
		self.is_edited = 1
		self.flags._was_edited = True

	def on_update(self):
		if self.flags.get("_was_edited"):
			notify_dm_message_edited(self)
			resync_dm_thread_last_message_on_edit(self)

	def on_trash(self):
		"""Deletes a DM for everyone; ownership itself is enforced by has_dm_message_permission."""
		if self.attachment:
			file_name = frappe.db.get_value("File", {"file_url": self.attachment}, "name")
			if file_name:
				frappe.delete_doc("File", file_name)

		notify_dm_message_deleted(self)
		resync_dm_thread_last_message_on_trash(self)
