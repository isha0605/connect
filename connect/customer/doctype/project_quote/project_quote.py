# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from connect.customer.doctype.customer_project.project_notifications import notify_quote_update

# Once the customer shows interest in the partner's quote, the partner learns who they are.
REVEALING_STATUSES = ("Interested", "Hire Requested", "Hired")


class ProjectQuote(Document):
	"""One partner a customer's brief went to, and where that partner stands: Awaiting until
	they quote, then Quoted, and Interested or Not Interested once the customer decides.
	The quote itself is also a Quote message in their thread, which Messaging shows.

	For the partner's sales team it is one requirement on their lead for the customer (the
	Partner Lead), which holds the stage and owner of all the customer's requirements."""

	def before_insert(self):
		if self.thread and not self.lead:
			from connect.partner.doctype.partner_lead.partner_lead import lead_for_requirement

			self.lead = lead_for_requirement(self.partner, self.thread)

	def on_update(self):
		notify_quote_update(self)
		self._reveal_customer()
		if self.status == "Hired" and self.has_value_changed("status"):
			self._win_lead()

	def _reveal_customer(self):
		if self.thread and self.status in REVEALING_STATUSES and self.has_value_changed("status"):
			frappe.get_doc("Connect Thread", self.thread).reveal_customer()

	def _win_lead(self):
		"""The partner accepting the hire wins the lead: the customer joins their Customers."""
		from connect.partner.doctype.partner_customer.partner_customer import add_won_customer

		if self.lead:
			frappe.get_doc("Partner Lead", self.lead).win()
		add_won_customer(self)
