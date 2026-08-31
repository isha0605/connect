# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Adds a MariaDB FULLTEXT index on Partner's searchable text fields, to back relevance-ranked partner search."""
	if frappe.db.db_type != "mariadb":
		return

	if not frappe.db.table_exists("Partner"):
		return

	statistics = frappe.qb.Schema("information_schema").statistics
	existing = (
		frappe.qb.from_(statistics)
		.select(statistics.index_name)
		.where(statistics.table_schema == frappe.qb.functions("DATABASE"))
		.where(statistics.table_name == "tabPartner")
		.where(statistics.index_name == "partner_fts")
	).run()
	if existing:
		return

	frappe.db.sql_ddl(
		"""
		ALTER TABLE `tabPartner`
		ADD FULLTEXT INDEX partner_fts (partner_name, tagline, description, industry, city, country)
		"""
	)
