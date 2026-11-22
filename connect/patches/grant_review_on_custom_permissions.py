import frappe

from connect.roles import PARTNER_MANAGER_ROLE

REVIEWED_DOCTYPES = ("Partner Application", "Certificate Application", "Partner Review")


def execute():
	"""A site that customised these doctypes' permissions keeps Custom DocPerm rows, and those hide
	the doctype's own rows, so the new Review right is granted there too. Without it, Partner
	Managers would lose approvals and review emails on such a site."""
	if not frappe.db.has_column("Custom DocPerm", "review"):
		return

	Perm = frappe.qb.DocType("Custom DocPerm")
	(
		frappe.qb.update(Perm)
		.set(Perm.review, 1)
		.where(
			Perm.parent.isin(REVIEWED_DOCTYPES)
			& Perm.role.isin((PARTNER_MANAGER_ROLE, "System Manager"))
			& (Perm.permlevel == 0)
		)
	).run()
	for doctype in REVIEWED_DOCTYPES:
		frappe.clear_cache(doctype=doctype)
