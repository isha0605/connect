# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Drops Partner's founded_years_ago column, left from a field that was removed. The profile works
	the value out from foundation_date each time instead, so the column is never read."""
	if frappe.db.has_column("Partner", "founded_years_ago"):
		frappe.db.sql_ddl("alter table `tabPartner` drop column `founded_years_ago`")
		frappe.client_cache.delete_value("table_columns::tabPartner")
