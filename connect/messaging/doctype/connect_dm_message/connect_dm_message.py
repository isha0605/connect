
import frappe
from frappe import _
from frappe.model.document import Document

from connect.permissions import _dm_thread_pair


class ConnectDMMessage(Document):
	def validate(self):
		if self.message_type == "File" and not self.attachment:
			frappe.throw(_("A file message must have an attachment"))
		if not self.is_new():
			self._validate_edit()

	def _validate_edit(self):
		"""sender's own-message-only edit rule."""
		user = frappe.session.user
		_dm_thread_pair(self.dm_thread, user)
		if self.sender != user:
			frappe.throw(_("You can only edit your own messages"), frappe.PermissionError)
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
			from connect.notifications import notify_dm_message_edited

			notify_dm_message_edited(self)

	def on_trash(self):
		"""DM counterpart to Connect Message's own-message-only delete rule."""
		from connect.notifications import notify_dm_message_deleted

		user = frappe.session.user
		_dm_thread_pair(self.dm_thread, user)
		if self.sender != user:
			frappe.throw(_("You can only delete your own messages"), frappe.PermissionError)

		if self.attachment:
			file_name = frappe.db.get_value("File", {"file_url": self.attachment}, "name")
			if file_name:
				frappe.delete_doc("File", file_name, ignore_permissions=True)

		notify_dm_message_deleted(self)
