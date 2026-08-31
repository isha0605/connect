# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Enforce (customer, partner) uniqueness on Shortlist at the DB level, so a
	duplicate row can never be created — not through the UI, a direct API call,
	a bug, or a race condition — replacing the app-level frappe.db.exists check
	that used to run on every insert (see Shortlist.validate, now removed).

	De-dupes first (defensive — none exist as of writing, but a patch has to be
	safe on any environment's data): keeps the oldest row per (customer, partner)
	pair and deletes the rest, since ADD UNIQUE fails outright if any duplicates
	are already present.
	"""
	if not frappe.db.table_exists("Shortlist"):
		return

	duplicates = frappe.db.sql(
		"""
		SELECT customer, partner
		FROM `tabShortlist`
		GROUP BY customer, partner
		HAVING COUNT(*) > 1
		""",
		as_dict=True,
	)
	for row in duplicates:
		names = frappe.db.get_all(
			"Shortlist",
			filters={"customer": row.customer, "partner": row.partner},
			pluck="name",
			order_by="creation asc",
		)
		for name in names[1:]:
			frappe.delete_doc("Shortlist", name, ignore_permissions=True, delete_permanently=True)

	frappe.db.add_unique("Shortlist", ["customer", "partner"])
