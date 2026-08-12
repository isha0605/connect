import frappe

from connect.connect.roles import CUSTOMER_GUEST_ROLE, PARTNER_GUEST_ROLE, _GUEST_ROLE_BY_SIDE, _set_role


def execute():
	"""connect.patches.backfill_thread_member_company_membership (earlier in this same
	rollout) fixed a permission outage by making every thread-only participant a full
	Connect Customer Member/Connect Partner Member row. That was wrong: those doctypes are
	supposed to mean 'real company member' (roster visibility, admin-transfer eligible, can
	start new threads) — not 'was added to one chat thread'. This patch corrects it:

	1. Creates the new guest roles, the right mechanism for thread-only messaging access.
	2. Removes the specific rows that patch wrongly created on this site (identified
	   directly — there's no data-only way to distinguish a wrongly-backfilled row from a
	   real one after the fact).
	3. Grants the guest role to every thread-only member instead, generally enough to also
	   self-correct on any other site that ran the same flawed patch.
	"""
	for role_name in (CUSTOMER_GUEST_ROLE, PARTNER_GUEST_ROLE):
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 0,
			}).insert(ignore_permissions=True)

	wrongly_added = [
		("Connect Customer Member", "pri@gmail.com"),
		("Connect Partner Member", "priyanshi@gmail.com"),
		("Connect Partner Member", "neha@gmail.com"),
		("Connect Partner Member", "tridotmember@gmail.com"),
	]
	for doctype, user in wrongly_added:
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
		if frappe.db.exists(company_doctype, {"user": tm.user}):
			continue  # real company member — already has full access via the main role

		_set_role(tm.user, _GUEST_ROLE_BY_SIDE[tm.side], True)
