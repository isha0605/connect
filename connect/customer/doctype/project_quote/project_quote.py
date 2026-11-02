# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from connect.customer.doctype.customer_project.project_notifications import notify_quote_update
from connect.permissions import _is_active_partner_member

# Once the customer shows interest in the partner's quote, the partner learns who they are.
REVEALING_STATUSES = ("Interested", "Hire Requested", "Hired")


class ProjectQuote(Document):
	"""One partner a customer's brief went to, and where that partner stands: Awaiting until
	they quote, then Quoted, and Interested or Not Interested once the customer decides.
	The quote itself is also a Quote message in their thread, which Messaging shows.

	It is also the partner's lead for that brief: the stage, owner and probability their
	sales team works it with, on the Leads page."""

	def validate(self):
		if self.has_value_changed("status") and self.status == "Hired":
			self.lead_stage = "Won"
		self._validate_lost_reason()
		self._validate_lead_owner()

	def on_update(self):
		notify_quote_update(self)
		self._add_lead_owner_to_thread()
		self._reveal_customer()
		self._convert_to_customer()

	def _validate_lost_reason(self):
		if self.lead_stage != "Lost":
			self.lost_reason = None
		elif not self.lost_reason:
			frappe.throw(_("Pick why the lead was lost."))

	def _validate_lead_owner(self):
		if not self.lead_owner or not self.has_value_changed("lead_owner"):
			return
		if not _is_active_partner_member(self.partner, self.lead_owner):
			frappe.throw(_("{0} is not on your team.").format(self.lead_owner))

	def _add_lead_owner_to_thread(self):
		"""Whoever works the lead has to read and answer the customer."""
		if not self.lead_owner or not self.thread or not self.has_value_changed("lead_owner"):
			return
		from connect.messaging.doctype.connect_thread.connect_thread import ensure_partner_member

		ensure_partner_member(self.thread, self.lead_owner, frappe.session.user)

	def _reveal_customer(self):
		if self.thread and self.status in REVEALING_STATUSES and self.has_value_changed("status"):
			frappe.get_doc("Connect Thread", self.thread).reveal_customer()

	def _convert_to_customer(self):
		"""The partner accepting the hire wins the lead: the customer joins their Customers."""
		if self.status != "Hired" or not self.has_value_changed("status"):
			return
		from connect.partner.doctype.partner_customer.partner_customer import add_won_customer

		add_won_customer(self)
