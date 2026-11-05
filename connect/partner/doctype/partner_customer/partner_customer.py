# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from connect.partner.doctype.connect_partner_member.connect_partner_member import CUSTOMER_ACCESS
from connect.permissions import _has_partner_access


# Waiting for the team to approve linking the customer's Frappe Cloud account.
WANTS_TO_LINK = "Wants to link"


class PartnerCustomer(Document):
	"""A customer a partner works with. A Connect customer becomes one when the partner accepts
	their hire request. They start as Wants to link, and Onboarding once the team approves
	the link. One per partner and customer."""

	def validate(self):
		if self.assigned_to and self.has_value_changed("assigned_to"):
			if not _has_partner_access(self.partner, self.assigned_to, CUSTOMER_ACCESS):
				frappe.throw(_("{0} can't look after customers on your team.").format(self.assigned_to))
		if not self.is_new() and self.has_value_changed("stage"):
			self._validate_stage_change()

	def is_linked(self) -> bool:
		return self.stage != WANTS_TO_LINK

	def _validate_stage_change(self):
		"""A link is approved once, into Onboarding, and never taken back to Wants to link."""
		before = self.get_doc_before_save().stage
		if self.stage == WANTS_TO_LINK:
			frappe.throw(_("A linked customer can't go back to Wants to link."))
		if before == WANTS_TO_LINK:
			if self.stage != "Onboarding":
				frappe.throw(_("Approve the link first: the customer starts at Onboarding."))
			self.linked_on = now_datetime()


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
				"stage": WANTS_TO_LINK,
				"source": "Connect",
				"assigned_to": quote.lead and frappe.db.get_value("Partner Lead", quote.lead, "assigned_to"),
				"quote": quote.name,
				"project": quote.customer_project,
				"converted_on": now_datetime(),
			}
		)
		.insert(ignore_permissions=True)
		.name
	)
