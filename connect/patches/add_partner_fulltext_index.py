# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Add a MariaDB FULLTEXT index on Partner's searchable text fields, backing
	relevance-ranked full-text search in connect.api.search_partners. FULLTEXT +
	MATCH/AGAINST is MariaDB/MySQL-specific; skipped on other backends."""
	if frappe.db.db_type != "mariadb":
		return

	if not frappe.db.table_exists("Partner"):
		return

	existing = frappe.db.sql(
		"""
		SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS
		WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tabPartner' AND INDEX_NAME = 'partner_fts'
		"""
	)
	if existing:
		return

	frappe.db.sql_ddl(
		"""
		ALTER TABLE `tabPartner`
		ADD FULLTEXT INDEX partner_fts (partner_name, tagline, description, industry, city, country)
		"""
	)
