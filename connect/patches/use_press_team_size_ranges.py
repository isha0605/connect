# Copyright (c) 2026
# For license information, please see license.txt

import frappe

OLD_RANGES = ("201-500", "500+")
NEW_RANGE = "201+"

# Partner fields that hold a partner's team size, by DocType.
TEAM_SIZE_FIELDS = {"Partner": "team_size", "Partner Application": "employee_range"}


def execute():
	"""Moves partner team sizes above 200 to Press's single "201+" range."""
	for doctype, fieldname in TEAM_SIZE_FIELDS.items():
		table = frappe.qb.DocType(doctype)
		(
			frappe.qb.update(table)
			.set(table[fieldname], NEW_RANGE)
			.where(table[fieldname].isin(OLD_RANGES))
		).run()
