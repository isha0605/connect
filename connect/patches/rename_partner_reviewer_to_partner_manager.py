import frappe

from connect.roles import PARTNER_MANAGER_ROLE


def execute():
	"""Renames the Partner Reviewer role to Partner Manager, keeping every user who holds it and
	every permission row that names it. Runs before the doctype sync, which would otherwise create
	an empty Partner Manager role first and block the rename."""
	if frappe.db.exists("Role", "Partner Reviewer") and not frappe.db.exists("Role", PARTNER_MANAGER_ROLE):
		frappe.rename_doc("Role", "Partner Reviewer", PARTNER_MANAGER_ROLE, force=True, show_alert=False)
