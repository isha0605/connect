# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class CustomerTeamMember(Document):
	def remove(self, removed_by):
		"""Removes this person from the company roster, revoking their thread access but leaving their past messages untouched."""
		from connect.permissions import _is_customer_admin

		if not _is_customer_admin(self.customer, removed_by):
			frappe.throw(_("Only an admin can remove a team member"), frappe.PermissionError)
		if self.is_removed:
			frappe.throw(_("{0} has already left").format(self.user))

		self.is_removed = 1
		self.removed_on = now_datetime()
		self.save(ignore_permissions=True)

		for row in frappe.get_all(
			"Connect Thread Member",
			filters={"user": self.user, "side": "Customer", "is_removed": 0},
			fields=["name", "thread"],
		):
			frappe.get_doc("Connect Thread", row.thread).remove_member(row.name, removed_by)
