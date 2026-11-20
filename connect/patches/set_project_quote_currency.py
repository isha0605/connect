# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Quotes now keep their currency. Every quote made before was typed in rupees."""
	quote = frappe.qb.DocType("Project Quote")
	(
		frappe.qb.update(quote)
		.set(quote.currency, "INR")
		.where(quote.currency.isnull() | (quote.currency == ""))
	).run()
