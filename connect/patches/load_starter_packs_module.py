# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Makes the schema sync see the new Starter Packs module, which the Starter Pack doctypes moved into
	from Customer.

	Migrate reads the list of modules from the cache before it clears the cache, so on the first migrate
	after the move it still has the old list. The sync then never looks in the new folder, and the orphan
	cleanup that follows can't find the doctypes' code under Customer and deletes their DocType records.
	Rebuilding the list here, before the sync, avoids both. Safe to re-run.
	"""
	frappe.cache.delete_value("app_modules")
	frappe.client_cache.delete_value("installed_app_modules")
	frappe.setup_module_map()
