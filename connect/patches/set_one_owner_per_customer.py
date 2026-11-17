import frappe

from connect.patches.set_one_owner_per_partner import set_one_owner


def execute():
	"""Customer team members moved from `is_admin` to one `access` field, and a company now has one
	Owner. In each company the earliest admin stays Owner, every other admin becomes an Admin, and
	everyone else is a Member."""
	Member = frappe.qb.DocType("Customer Team Member")
	(
		frappe.qb.update(Member)
		.set(Member.access, "Member")
		.where(Member.access.isnull() | (Member.access == ""))
	).run()
	set_one_owner("Customer Team Member", "customer")
