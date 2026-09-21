# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ConnectMessageReaction(Document):
	def validate(self):
		self.emoji = (self.emoji or "").strip()
		if not self.emoji:
			frappe.throw(_("Pick an emoji to react with"))

		# Compared in Python: the database's default collation treats different emoji as equal.
		same_user_reactions = frappe.get_all(
			"Connect Message Reaction",
			filters={"message": self.message, "is_dm": self.is_dm, "user": self.user, "name": ["!=", self.name]},
			pluck="emoji",
		)
		if self.emoji in same_user_reactions:
			frappe.throw(_("You have already reacted with this emoji"))
