# Copyright (c) 2026
# For license information, please see license.txt

import frappe

OLD_DOCTYPE = "Partner Pack"


def execute():
	"""Removes Partner Pack, the per-partner pack prices, now that Frappe sets every pack's
	price in Starter Pack. Its rows are dropped with it: nothing reads them.

	Frappe's delete_doc leaves the table behind, so it is dropped explicitly. Safe to re-run.
	"""
	if frappe.db.exists("DocType", OLD_DOCTYPE):
		frappe.delete_doc("DocType", OLD_DOCTYPE, force=True, ignore_missing=True)
	frappe.db.sql_ddl(f"drop table if exists `tab{OLD_DOCTYPE}`")
