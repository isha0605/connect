import frappe

from connect.roles import CONSULTANT_ROLE


def execute():
	"""Creates the Frappe Consultant role if missing. A System Manager gives it to a User by
	hand; connect.partner.consultants does the rest."""
	if not frappe.db.exists("Role", CONSULTANT_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": CONSULTANT_ROLE, "desk_access": 0}).insert(
			ignore_permissions=True
		)
