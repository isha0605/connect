# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Removes the "Book a slot" feature's data and schema now that its code is gone.

	Deletes the Booking-type messages through delete_doc (not raw SQL) so each thread's denormalized
	last-message preview is re-synced, then drops the Connect Booking and Partner Booking Slot doctypes.
	Frappe's delete_doc leaves the tables behind, so they're dropped explicitly. Safe to re-run.
	"""
	if frappe.db.table_exists("Connect Message"):
		for name in frappe.get_all("Connect Message", filters={"message_type": "Booking"}, pluck="name"):
			frappe.delete_doc("Connect Message", name, force=True, ignore_permissions=True)

	for doctype in ("Connect Booking", "Partner Booking Slot"):
		if frappe.db.exists("DocType", doctype):
			frappe.delete_doc("DocType", doctype, force=True, ignore_missing=True)
		frappe.db.sql_ddl(f"drop table if exists `tab{doctype}`")
