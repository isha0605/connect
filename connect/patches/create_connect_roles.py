import frappe

from connect.connect.roles import CUSTOMER_ROLE, PARTNER_ROLE


def execute():
	"""Introduces Connect Customer / Connect Partner as the doctype-level access gate for
	thread data (see connect.connect.roles) — this patch creates the roles and backs the
	new grant/revoke hooks up to every membership that already exists, so no one loses
	access when the 'All' role permission is eventually removed in a later change."""
	for role_name in (CUSTOMER_ROLE, PARTNER_ROLE):
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 0,
			}).insert(ignore_permissions=True)

	for row in frappe.get_all("Connect Customer Member", fields=["user"]):
		user_doc = frappe.get_doc("User", row.user)
		user_doc.flags.ignore_permissions = True
		user_doc.add_roles(CUSTOMER_ROLE)

	for row in frappe.get_all("Connect Partner Member", fields=["user"]):
		user_doc = frappe.get_doc("User", row.user)
		user_doc.flags.ignore_permissions = True
		user_doc.add_roles(PARTNER_ROLE)
