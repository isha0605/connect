# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe.model.utils.rename_field import rename_field
from frappe.query_builder.functions import Count


def execute():
	"""Renames Partner.is_featured to show_in_website, the name frappe.io uses for the same switch.
	Moves each partner's value, checks it moved, then drops the old column. Safe to re-run."""
	if not frappe.db.has_column("Partner", "is_featured"):
		return

	listed_before = count_listed("is_featured")
	rename_field("Partner", "is_featured", "show_in_website")
	# rename_field only prints when it cannot copy, so check before the old values are dropped.
	if count_listed("show_in_website") < listed_before:
		frappe.throw(
			"Only some Partner.is_featured values moved to show_in_website. Kept is_featured. Run bench migrate again."
		)

	frappe.db.sql_ddl("alter table `tabPartner` drop column `is_featured`")
	frappe.client_cache.delete_value("table_columns::tabPartner")


def count_listed(column: str) -> int:
	# Reads the column directly: is_featured is no longer a Partner field, so frappe.db.count rejects it.
	partner = frappe.qb.DocType("Partner")
	return frappe.qb.from_(partner).select(Count("*")).where(partner[column] == 1).run()[0][0]
