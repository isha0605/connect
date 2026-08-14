# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Shortlist(Document):
	def validate(self):
		duplicate = frappe.db.exists(
			"Shortlist",
			{"customer": self.customer, "partner": self.partner, "name": ["!=", self.name]},
		)
		if duplicate:
			frappe.throw(f"{self.partner} is already shortlisted for {self.customer}.")


def _customer_names_for_user(user):
	return frappe.get_all("Customer Team Member", filters={"user": user}, pluck="parent")


def get_permission_query_conditions(user):
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return ""
	customers = _customer_names_for_user(user)
	if not customers:
		return "1=0"
	names = ", ".join(frappe.db.escape(c) for c in customers)
	return f"`tabShortlist`.customer in ({names})"


def has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return True
	return doc.customer in _customer_names_for_user(user)
