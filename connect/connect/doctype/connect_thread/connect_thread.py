# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class ConnectThread(Document):
	def validate(self):
		existing = frappe.db.exists(
			"Connect Thread",
			{"customer": self.customer, "partner": self.partner, "name": ["!=", self.name]},
		)
		if existing:
			frappe.throw(
				_("A thread between {0} and {1} already exists: {2}").format(
					self.customer, self.partner, existing
				)
			)

		if self.status == "Closed" and not self.closed_on:
			self.closed_on = now_datetime()
		if self.status == "Open":
			self.closed_by = None
			self.closed_on = None
