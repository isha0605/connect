import frappe


def execute():
	"""Partner members gained an access level (Sales, Finance or Member; Owner stays `is_admin`).
	Everyone already on a team starts as Member, and a removed owner stops being one."""
	Member = frappe.qb.DocType("Connect Partner Member")
	(
		frappe.qb.update(Member)
		.set(Member.access, "Member")
		.where(Member.access.isnull() | (Member.access == ""))
	).run()
	(
		frappe.qb.update(Member)
		.set(Member.is_admin, 0)
		.where((Member.is_removed == 1) & (Member.is_admin == 1))
	).run()
