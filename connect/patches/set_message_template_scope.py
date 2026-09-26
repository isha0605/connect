import frappe


def execute():
	"""`scope` replaces `is_global` as the template's visibility; the new column defaults every row
	to Personal, so only the global ones need moving."""
	frappe.db.set_value("Connect Message Template", {"is_global": 1}, "scope", "Global", update_modified=False)
