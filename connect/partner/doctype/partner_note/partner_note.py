# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PartnerNote(Document):
	"""A note a partner's team keeps about one customer, shown on the customer's leads and on the
	customer's page. connect.partner.doctype.partner_customer.customer_records serves it."""
