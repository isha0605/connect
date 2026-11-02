# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from connect.permissions import _is_active_partner_member


class PartnerCustomer(Document):
	"""A customer a partner works with. A Connect customer becomes one when the partner accepts
	their hire request, and starts Onboarding. One per partner and customer."""

	def validate(self):
		if self.assigned_to and self.has_value_changed("assigned_to"):
			if not _is_active_partner_member(self.partner, self.assigned_to):
				frappe.throw(_("{0} is not on your team.").format(self.assigned_to))


def add_won_customer(quote) -> str:
	"""The partner's customer record for the customer whose lead they just won, made the first
	time. A customer who hires them again keeps the record they already have."""
	customer = frappe.db.get_value("Connect Thread", quote.thread, "customer")
	existing = frappe.db.get_value("Partner Customer", {"partner": quote.partner, "customer": customer}, "name")
	if existing:
		return existing
	# A system step on the partner accepting the hire; neither side writes this record directly.
	return (
		frappe.get_doc(
			{
				"doctype": "Partner Customer",
				"partner": quote.partner,
				"customer": customer,
				"stage": "Onboarding",
				"source": "Connect",
				"assigned_to": quote.lead_owner,
				"quote": quote.name,
				"project": quote.customer_project,
				"converted_on": now_datetime(),
			}
		)
		.insert(ignore_permissions=True)
		.name
	)
