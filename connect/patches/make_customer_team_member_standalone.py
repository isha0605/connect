import frappe

from connect.roles import CUSTOMER_ROLE


def execute():
	"""Backfills Customer Team Member's new `customer` field and re-grants its role, now that the doctype is standalone instead of a child table."""
	if not frappe.db.has_column("Customer Team Member", "parent"):
		return

	CTM = frappe.qb.DocType("Customer Team Member")
	rows = (
		frappe.qb.from_(CTM)
		.select(CTM.name, CTM.parent)
		.where(CTM.parent.isnotnull() & (CTM.parent != ""))
		.where(CTM.customer.isnull() | (CTM.customer == ""))
	).run(as_dict=True)
	for row in rows:
		frappe.db.set_value("Customer Team Member", row.name, "customer", row.parent, update_modified=False)

	for user in frappe.get_all("Customer Team Member", pluck="user", distinct=True):
		user_doc = frappe.get_doc("User", user)
		user_doc.flags.ignore_permissions = True
		user_doc.add_roles(CUSTOMER_ROLE)
