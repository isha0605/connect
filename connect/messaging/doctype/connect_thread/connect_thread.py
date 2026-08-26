# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class ConnectThread(Document):
	def validate(self):
		if not self.is_new():
			# customer/partner define which two companies' history lives in this thread —
			# the doctype otherwise grants "write" to any partner admin (so they can close
			# it), and without this, that same write access could reassign the thread to an
			# unrelated customer, silently handing them another company's message history
			# the next time that customer messages this partner.
			prev = frappe.db.get_value("Connect Thread", self.name, ["customer", "partner"], as_dict=True)
			if prev and (prev.customer != self.customer or prev.partner != self.partner):
				frappe.throw(_("A thread's customer and partner can't be changed after it's created"))

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
