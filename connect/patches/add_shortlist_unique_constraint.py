# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe.query_builder import functions as fn


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

	ShortlistTable = frappe.qb.DocType("Shortlist")
	duplicates = (
		frappe.qb.from_(ShortlistTable)
		.select(ShortlistTable.customer, ShortlistTable.partner)
		.groupby(ShortlistTable.customer, ShortlistTable.partner)
		.having(fn.Count("*") > 1)
	).run(as_dict=True)

	for row in duplicates:
		names = frappe.get_all(
			"Shortlist",
			filters={"customer": row.customer, "partner": row.partner},
			pluck="name",
			order_by="creation asc",
		)
		for name in names[1:]:
			frappe.delete_doc("Shortlist", name, ignore_permissions=True, delete_permanently=True)

	frappe.db.add_unique("Shortlist", ["customer", "partner"])
