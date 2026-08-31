# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_fullname, now_datetime


class ConnectThreadMember(Document):
	def validate(self):
		if frappe.db.exists(
			"Connect Thread Member",
			{"thread": self.thread, "user": self.user, "is_removed": 0, "name": ["!=", self.name]},
		):
			frappe.throw(_("{0} is already an active member of this thread").format(self.user))

		if not self.added_on:
			self.added_on = now_datetime()

		if self.is_removed and not self.removed_on:
			self.removed_on = now_datetime()
		if not self.is_removed:
			self.removed_on = None

	def make_admin(self, user):
		"""Promotes this thread member to company admin, creating a company membership row for them if they don't have one yet."""
		from connect.permissions import _is_customer_admin, _is_partner_admin

		if self.is_removed:
			frappe.throw(_("A removed member can't be made admin"))

		thread_doc = frappe.get_doc("Connect Thread", self.thread)

		if self.side == "Customer":
			company = thread_doc.customer
			authorized = _is_customer_admin(company, user)
		elif self.side == "Partner":
			company = thread_doc.partner
			authorized = _is_partner_admin(company, user)
		else:
			frappe.throw(_("Invalid side"))

		if not authorized:
			frappe.throw(_("Only an admin of your own side can do this"), frappe.PermissionError)

		if self.side == "Customer":
			my_row = frappe.db.get_value("Customer Team Member", {"customer": company, "user": user}, "name")
			if my_row:
				frappe.db.set_value("Customer Team Member", my_row, "is_admin", 0)

			target_row = frappe.db.get_value(
				"Customer Team Member", {"customer": company, "user": self.user}, "name"
			)
			if target_row:
				frappe.db.set_value("Customer Team Member", target_row, "is_admin", 1)
			else:
				frappe.get_doc({
					"doctype": "Customer Team Member",
					"customer": company,
					"user": self.user,
					"full_name": get_fullname(self.user),
					"is_admin": 1,
				}).insert(ignore_permissions=True)
		else:
			my_row = frappe.db.get_value("Connect Partner Member", {"partner": company, "user": user}, "name")
			if my_row:
				frappe.db.set_value("Connect Partner Member", my_row, "is_admin", 0)

			target_row = frappe.db.get_value(
				"Connect Partner Member", {"partner": company, "user": self.user}, "name"
			)
			if target_row:
				frappe.db.set_value("Connect Partner Member", target_row, "is_admin", 1)
			else:
				frappe.get_doc({
					"doctype": "Connect Partner Member",
					"partner": company,
					"user": self.user,
					"is_admin": 1,
				}).insert(ignore_permissions=True)
