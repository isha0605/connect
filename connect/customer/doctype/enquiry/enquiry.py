# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import validate_email_address

from connect.customer.doctype.customer.customer import get_customer_for_user

# What a visitor fills in; status, source and the account links are Connect's to set.
VISITOR_FIELDS = (
	"first_name",
	"last_name",
	"email",
	"phone",
	"company_name",
	"designation",
	"employees",
	"current_software",
	"industry",
	"state",
	"message",
)


class Enquiry(Document):
	"""A visitor asking Frappe's team to call them, from a Contact us form. The team works
	through them in Desk; a Notification emails each new one."""

	def before_insert(self):
		user = frappe.session.user
		if user != "Guest":
			self.user = user
			self.customer = get_customer_for_user(user)

	def validate(self):
		for field in VISITOR_FIELDS:
			if isinstance(self.get(field), str):
				self.set(field, self.get(field).strip())
		self.email = (self.email or "").lower()
		validate_email_address(self.email, throw=True)


def submit_enquiry(values, source=None):
	"""Saves a Contact us form. Only the form's own fields are taken from the request."""
	doc = frappe.new_doc("Enquiry")
	doc.update({field: values.get(field) for field in VISITOR_FIELDS})
	if source:
		doc.source = source
	# Visitors, signed in or not, send enquiries without reading any; only System Managers read them.
	doc.insert(ignore_permissions=True)
	return {"name": doc.name}
