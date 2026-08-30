import frappe

from connect.connect.roles import CUSTOMER_ROLE


def execute():
	"""Customer Team Member just became a standalone doctype (it was a child table of
	Customer) so its after_insert/on_trash role-grant hooks (see connect.connect.roles)
	actually fire. As a child table, rows were always written via
	`customer_doc.append("team", ...); customer_doc.save()` — Frappe writes child rows with
	raw db_insert/db_update during the parent's save, which never runs the child doctype's
	own after_insert/on_trash controller hooks. So every Customer Team Member row ever
	created (every signup, every make_thread_admin promotion) silently never granted its
	user the Connect Customer role, even after hooks.py was wired up for it.

	Backfills the new `customer` link field from the old child-table `parent` column (still
	physically present on the table — schema sync only adds columns, it doesn't drop ones no
	longer in the DocType), then grants CUSTOMER_ROLE to every row's user so nobody who
	should already have messaging access is still missing it."""
	if not frappe.db.has_column("Customer Team Member", "parent"):
		return

	rows = frappe.db.sql(
		"""select name, parent from `tabCustomer Team Member`
		where parent is not null and parent != '' and (customer is null or customer = '')""",
		as_dict=True,
	)
	for row in rows:
		frappe.db.set_value("Customer Team Member", row.name, "customer", row.parent, update_modified=False)

	for user in frappe.get_all("Customer Team Member", pluck="user", distinct=True):
		user_doc = frappe.get_doc("User", user)
		user_doc.flags.ignore_permissions = True
		user_doc.add_roles(CUSTOMER_ROLE)
