# Copyright (c) 2026
# For license information, please see license.txt

import frappe

CARD_TYPES = ("Quote", "Hire Request")


def execute():
	"""Quote and hire request cards now say their quote's currency. Every card sent before was in rupees."""
	for name, content in frappe.get_all(
		"Connect Message",
		filters={"message_type": ["in", CARD_TYPES]},
		fields=["name", "content"],
		as_list=True,
	):
		card = frappe.parse_json(content or "{}") or {}
		if card.get("currency"):
			continue
		card["currency"] = "INR"
		frappe.db.set_value("Connect Message", name, "content", frappe.as_json(card), update_modified=False)
