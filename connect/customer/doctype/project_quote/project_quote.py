# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProjectQuote(Document):
	"""One partner a customer's brief went to, and where that partner stands: Awaiting until
	they quote, then Quoted, and Interested or Not Interested once the customer decides.
	The quote itself is also a Quote message in their thread, which Messaging shows."""

	pass
