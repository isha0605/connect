# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

# What a person can do at their partner firm. Owner is `is_admin`; the rest are `access`.
OWNER = "Owner"
ACCESS_LEVELS = (OWNER, "Sales", "Finance", "Member")


class ConnectPartnerMember(Document):
	def validate(self):
		if frappe.db.exists(
			"Connect Partner Member",
			{"partner": self.partner, "user": self.user, "name": ["!=", self.name]},
		):
			frappe.throw(_("{0} is already a member of {1}").format(self.user, self.partner))

		self._keep_an_owner()

	def _keep_an_owner(self):
		"""A firm can have several owners, but never none: its chats and requests go to them."""
		before = self.get_doc_before_save()
		was_owner = bool(before and before.is_admin and not before.is_removed)
		if not was_owner or (self.is_admin and not self.is_removed):
			return

		if not frappe.db.exists(
			"Connect Partner Member",
			{"partner": self.partner, "is_admin": 1, "is_removed": 0, "name": ["!=", self.name]},
		):
			frappe.throw(_("Make someone else an owner first. A firm needs at least one owner."))

	@property
	def access_level(self) -> str:
		return OWNER if self.is_admin else (self.access or "Member")

	def set_access_level(self, level: str, changed_by: str):
		"""Makes this person an owner, or gives them Sales, Finance or Member access."""
		from connect.permissions import _is_partner_admin

		if not _is_partner_admin(self.partner, changed_by):
			frappe.throw(_("Only an owner can change what people can do"), frappe.PermissionError)
		if level not in ACCESS_LEVELS:
			frappe.throw(_("Pick Owner, Sales, Finance or Member"))
		if self.is_removed:
			frappe.throw(_("{0} has left the team").format(self.user))

		self.is_admin = int(level == OWNER)
		if level != OWNER:
			self.access = level
		self.save(ignore_permissions=True)

	def remove(self, removed_by):
		"""Removes this person from the company roster, revoking their thread access but leaving their past messages untouched."""
		from connect.permissions import _is_partner_admin

		if not _is_partner_admin(self.partner, removed_by):
			frappe.throw(_("Only an admin can remove a team member"), frappe.PermissionError)
		if self.is_removed:
			frappe.throw(_("{0} has already left").format(self.user))

		# A removed owner stops being one, so every `is_admin` check drops them too.
		self.is_removed = 1
		self.is_admin = 0
		self.removed_on = now_datetime()
		self.save(ignore_permissions=True)

		for row in frappe.get_all(
			"Connect Thread Member",
			filters={"user": self.user, "side": "Partner", "is_removed": 0},
			fields=["name", "thread"],
		):
			frappe.get_doc("Connect Thread", row.thread).remove_member(row.name, removed_by)
