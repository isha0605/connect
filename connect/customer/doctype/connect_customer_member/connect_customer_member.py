# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ConnectCustomerMember(Document):
	def validate(self):
		if frappe.db.exists(
			"Connect Customer Member",
			{"customer": self.customer, "user": self.user, "name": ["!=", self.name]},
		):
			frappe.throw(_("{0} is already a member of {1}").format(self.user, self.customer))

		if self.is_admin and frappe.db.exists(
			"Connect Customer Member",
			{"customer": self.customer, "is_admin": 1, "name": ["!=", self.name]},
		):
			frappe.throw(_("{0} already has an admin. Only one admin is allowed per customer.").format(self.customer))
