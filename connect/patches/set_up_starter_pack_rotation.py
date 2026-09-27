# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Number the partners already approved for Starter Packs, in the order they were
	created, and create the rotation's pointer row so it can be locked from the start.
	Idempotent: partners that already have a rotation order keep it."""
	taken = set(
		frappe.get_all(
			"Partner",
			filters={"starter_pack": 1, "starter_pack_sequence": [">", 0]},
			pluck="starter_pack_sequence",
		)
	)
	next_sequence = max(taken, default=0) + 1
	for name in frappe.get_all(
		"Partner",
		filters={"starter_pack": 1, "starter_pack_sequence": ["in", [0, None]]},
		order_by="creation asc",
		pluck="name",
	):
		# db.set_value, not a save: numbering them shouldn't re-run a Partner's other
		# save hooks (logo normalising, story image fetching) or touch `modified`.
		frappe.db.set_value("Partner", name, "starter_pack_sequence", next_sequence, update_modified=False)
		next_sequence += 1

	if not frappe.db.sql(
		"select 1 from `tabSingles` where doctype = 'Starter Pack Settings' and field = 'rr_last_sequence'"
	):
		frappe.db.set_single_value("Starter Pack Settings", "rr_last_sequence", 0)
