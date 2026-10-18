import re

import frappe

from connect.notifications import _message_preview_text

AMOUNT = re.compile(r'"amount":\s*(\d+(?:\.\d+)?)')


def execute():
	"""Rewrites quote notifications that stored the raw quote JSON as their subject into the same
	"Quoted ₹…" text the thread preview shows. The subject was cut at 140 characters, so only the
	amount, which comes first, can be recovered."""
	logs = frappe.get_all(
		"Notification Log",
		filters={"document_type": "Connect Thread", "subject": ["like", '{%"amount"%']},
		fields=["name", "subject"],
	)

	for log in logs:
		match = AMOUNT.search(log.subject)
		if not match:
			continue

		quote = {"message_type": "Quote", "content": frappe.as_json({"amount": float(match.group(1))})}
		frappe.db.set_value(
			"Notification Log", log.name, "subject", _message_preview_text(quote), update_modified=False
		)
