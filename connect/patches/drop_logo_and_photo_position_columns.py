# Copyright (c) 2026
# For license information, please see license.txt

import frappe

COLUMNS = {
	"Partner": ("logo_position_x", "logo_position_y"),
	"Partner Team Member": ("photo_position_x", "photo_position_y"),
}


def execute():
	"""Drops the logo and founder photo position columns, left from fields that were removed. Logos and
	photos are always shown centred, so nothing reads them."""
	for doctype, columns in COLUMNS.items():
		for column in columns:
			if frappe.db.has_column(doctype, column):
				frappe.db.sql_ddl(f"alter table `tab{doctype}` drop column `{column}`")
		frappe.client_cache.delete_value(f"table_columns::tab{doctype}")
