import frappe

from connect.roles import REVIEWER_ROLE


def execute():
	"""Creates the Partner Reviewer role (internal staff, desk-facing) if missing. No
	membership table backs this role — an Administrator assigns it by hand."""
	if not frappe.db.exists("Role", REVIEWER_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": REVIEWER_ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)
