# Copyright (c) 2026
# For license information, please see license.txt

import frappe

OLD_DOCTYPE = "Connect Partner"
# The records that pointed at an old Connect Partner row before Partner replaced it.
LINKED_DOCTYPES = ("Connect Partner Member", "Connect Thread")


def execute():
	"""Removes the old Connect Partner doctype now that Partner holds every partner.

	Stops without deleting anything if a member or thread still points at one of its rows,
	because that row was never moved to Partner. Frappe's delete_doc leaves the table behind,
	so it is dropped explicitly. Safe to re-run.
	"""
	if frappe.db.table_exists(OLD_DOCTYPE):
		check_nothing_links_to_old_rows()

	if frappe.db.exists("DocType", OLD_DOCTYPE):
		frappe.delete_doc("DocType", OLD_DOCTYPE, force=True, ignore_missing=True)
	frappe.db.sql_ddl(f"drop table if exists `tab{OLD_DOCTYPE}`")


def check_nothing_links_to_old_rows():
	old_names = frappe.get_all(OLD_DOCTYPE, pluck="name")
	if not old_names:
		return

	for doctype in LINKED_DOCTYPES:
		names = frappe.get_all(doctype, filters={"partner": ["in", old_names]}, pluck="partner", distinct=True)
		unmoved = [name for name in names if not frappe.db.exists("Partner", name)]
		if unmoved:
			frappe.throw(
				f"{doctype} still points at {OLD_DOCTYPE} rows that are not in Partner: {', '.join(unmoved)}. "
				"Move them to Partner, then run the migration again.",
				title="Connect Partner rows not moved",
			)
