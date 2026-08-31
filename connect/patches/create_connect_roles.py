import frappe

from connect.roles import CUSTOMER_ROLE, PARTNER_ROLE


def execute():
	"""Creates the Connect Customer/Partner roles and grants them to every existing membership, so no one loses access."""
	for role_name in (CUSTOMER_ROLE, PARTNER_ROLE):
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 0,
			}).insert(ignore_permissions=True)

	if frappe.db.table_exists("Connect Customer Member"):
		for row in frappe.get_all("Connect Customer Member", fields=["user"]):
			user_doc = frappe.get_doc("User", row.user)
			user_doc.flags.ignore_permissions = True
			user_doc.add_roles(CUSTOMER_ROLE)

	for row in frappe.get_all("Connect Partner Member", fields=["user"]):
		user_doc = frappe.get_doc("User", row.user)
		user_doc.flags.ignore_permissions = True
		user_doc.add_roles(PARTNER_ROLE)
