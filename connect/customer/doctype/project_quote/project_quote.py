# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from connect.customer.doctype.customer_project.project_notifications import notify_quote_update


class ProjectQuote(Document):
	"""One partner a customer's brief went to, and where that partner stands: Awaiting until
	they quote, then Quoted, and Interested or Not Interested once the customer decides.
	The quote itself is also a Quote message in their thread, which Messaging shows."""

	def on_update(self):
		notify_quote_update(self)
