# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ConnectDMThread(Document):
	def validate(self):
		if self.user_a == self.user_b:
			frappe.throw(_("You can't start a conversation with yourself"))
		self._order_participants()

	def _order_participants(self):
		"""The unique (user_a, user_b) index only blocks a duplicate stored in the same order."""
		self.user_a, self.user_b = sorted([self.user_a, self.user_b])
