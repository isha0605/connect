
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from connect.notifications import (
	notify_dm_message_deleted,
	notify_dm_message_edited,
	notify_dm_message_pin_changed,
	resync_dm_thread_last_message_on_edit,
	resync_dm_thread_last_message_on_trash,
)


class ConnectDMMessage(Document):
	def validate(self):
		if self.message_type == "File" and not self.attachment:
			frappe.throw(_("A file message must have an attachment"))
		if self.message_type == "Text" and not (self.content or "").strip():
			frappe.throw(_("Message cannot be empty"))
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

	def pin(self, user):
		"""Pins this message to its conversation; a conversation can hold any number of pins. Pinning is
		posting-level access, so it needs the same write access as sending a message."""
		from connect.permissions import _dm_thread_pair

		_dm_thread_pair(self.dm_thread, user)
		self._set_pinned(1, user, now_datetime())
		notify_dm_message_pin_changed(self, user, True)

	def unpin(self, user):
		from connect.permissions import _dm_thread_pair

		_dm_thread_pair(self.dm_thread, user)
		self._set_pinned(0, None, None)
		notify_dm_message_pin_changed(self, user, False)

	def _set_pinned(self, is_pinned, pinned_by, pinned_at):
		# db_set so pinning someone else's message isn't blocked by the edit rules (and doesn't count as an
		# edit): the caller's access was already checked above.
		self.db_set(
			{"is_pinned": is_pinned, "pinned_by": pinned_by, "pinned_at": pinned_at}, update_modified=False
		)

	def on_trash(self):
		"""Deletes a DM for everyone; ownership itself is enforced by has_dm_message_permission."""
		if self.attachment:
			# Scoped to this message's own File: a forwarded copy shares the same file_url, and its File
			# must outlive this message.
			file_name = frappe.db.get_value(
				"File",
				{"file_url": self.attachment, "attached_to_doctype": "Connect DM Message", "attached_to_name": self.name},
				"name",
			)
			if file_name:
				frappe.delete_doc("File", file_name)

		frappe.db.delete("Connect Message Reaction", {"message": self.name, "is_dm": 1})

		notify_dm_message_deleted(self)
		resync_dm_thread_last_message_on_trash(self)
