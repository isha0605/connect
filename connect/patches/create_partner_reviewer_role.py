import frappe

from connect.roles import PARTNER_MANAGER_ROLE


def execute():
	"""Creates the Partner Manager role (internal staff, desk-facing) if missing. No
	membership table backs this role — an Administrator assigns it by hand."""
	if not frappe.db.exists("Role", PARTNER_MANAGER_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": PARTNER_MANAGER_ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)
