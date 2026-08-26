# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ConnectDMThread(Document):
	def pin(self, message, user):
		"""DM counterpart to Connect Thread's pin — either participant can pin, same as either
		can post."""
		from connect.notifications import notify_dm_thread_pin_changed
		from connect.permissions import _dm_thread_pair

		_dm_thread_pair(self.name, user)
		message_doc = frappe.get_doc("Connect DM Message", message)
		self.pinned_message = message_doc.name
		self.save(ignore_permissions=True)
		notify_dm_thread_pin_changed(self, message_doc, user)

	def unpin(self, user):
		from connect.notifications import notify_dm_thread_pin_changed
		from connect.permissions import _dm_thread_pair

		_dm_thread_pair(self.name, user)
		self.pinned_message = None
		self.save(ignore_permissions=True)
		notify_dm_thread_pin_changed(self, None, user)
