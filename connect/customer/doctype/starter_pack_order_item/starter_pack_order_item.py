# Copyright (c) 2026
# For license information, please see license.txt

from frappe.model.document import Document


class StarterPackOrderItem(Document):
	"""Snapshot of a pack at the moment it was ordered. Copied by the order, not
	fetched, so a later catalog price change never reprices a sale."""

	pass
