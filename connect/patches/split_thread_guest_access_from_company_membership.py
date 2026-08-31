import frappe

from connect.roles import CUSTOMER_GUEST_ROLE, PARTNER_GUEST_ROLE, _GUEST_ROLE_BY_SIDE, _set_role


def execute():
	"""Fixes a prior patch's mistake by moving thread-only participants from full company membership to a guest role."""
	for role_name in (CUSTOMER_GUEST_ROLE, PARTNER_GUEST_ROLE):
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 0,
			}).insert(ignore_permissions=True)

	# Real emails from the one site this ran on before Connect Customer Member was deleted
	# (see connect.patches.migrate_connect_company_to_customer_partner and the commit that
	# dropped the doctype) — kept out of source now that it's already run there; set via
	# site_config.json only if this ever needs to run again on a site with leftover rows.
	wrongly_added = frappe.conf.get("split_thread_guest_access_wrongly_added_rows") or []
	for doctype, user in wrongly_added:
		if not frappe.db.table_exists(doctype):
			continue
		name = frappe.db.get_value(doctype, {"user": user}, "name")
		if name:
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)

	thread_members = frappe.get_all("Connect Thread Member", fields=["user", "side"])
	seen = set()
	for tm in thread_members:
		key = (tm.user, tm.side)
		if key in seen:
			continue
		seen.add(key)

		company_doctype = "Connect Customer Member" if tm.side == "Customer" else "Connect Partner Member"
		if frappe.db.table_exists(company_doctype) and frappe.db.exists(company_doctype, {"user": tm.user}):
			continue  # real company member — already has full access via the main role

		_set_role(tm.user, _GUEST_ROLE_BY_SIDE[tm.side], True)
