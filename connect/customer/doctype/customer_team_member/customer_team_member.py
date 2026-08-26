# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class CustomerTeamMember(Document):
	def remove(self, removed_by):
		"""Removes this person from the company roster — the admin action for someone who's
		left. Revokes their access to every thread they were part of on the Customer side (via
		Connect Thread's own remove_member, so each thread also gets its own system message),
		but never touches anything they've already sent — messages and other activity stay
		exactly as they were."""
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
