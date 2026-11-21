# Copyright (c) 2026
# For license information, please see license.txt

import frappe

from connect.partner.press_integration import USD_TO_INR


def execute():
	"""Hourly rates were typed and shown in rupees for every partner. A partner outside India now
	shows their rate in dollars, so it is converted at the company rate Frappe Cloud uses, to
	whole dollars. The partner can correct it in their Listing."""
	for name, rate in frappe.get_all(
		"Partner",
		filters={"currency": "USD", "hourly_rate": [">", 0]},
		fields=["name", "hourly_rate"],
		as_list=True,
	):
		frappe.db.set_value("Partner", name, "hourly_rate", round(rate / USD_TO_INR), update_modified=False)
