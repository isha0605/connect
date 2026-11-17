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
	give_ownerless_companies_an_owner()


def give_ownerless_companies_an_owner():
	"""A customer's last admin could be removed before, which left nobody to manage its team. Such
	a company's earliest active member becomes its Owner."""
	Member = frappe.qb.DocType("Customer Team Member")
	with_owner = (
		frappe.qb.from_(Member).select(Member.customer).where((Member.access == "Owner") & (Member.is_removed == 0))
	)
	members = (
		frappe.qb.from_(Member)
		.select(Member.name, Member.customer)
		.where((Member.is_removed == 0) & Member.customer.notin(with_owner))
		.orderby(Member.creation)
	).run(as_dict=True)

	earliest = {}
	for row in members:
		earliest.setdefault(row.customer, row.name)
	if earliest:
		frappe.qb.update(Member).set(Member.access, "Owner").where(Member.name.isin(list(earliest.values()))).run()
