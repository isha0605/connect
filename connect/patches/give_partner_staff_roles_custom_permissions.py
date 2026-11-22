import frappe

from connect.roles import PARTNER_MANAGER_ROLE, STAFF_ROLE

PARTNER_DOCTYPES = (
	"Partner",
	"Partner Application",
	"Certificate Application",
	"Certificate Link Request",
	"Partner Certificate",
	"Partner Audit",
	"Partner Non Conformance",
	"Partner Review",
	"Review Request",
	"Partner Tier",
	"Partner Lead",
	"Partner Customer",
	"Partner Note",
	"Partner Follow Up",
	"Partner Chat Reply",
	"Partner CRM Settings",
	"Connect Partner Member",
)
STAFF_ROLES = (PARTNER_MANAGER_ROLE, STAFF_ROLE)


def execute():
	"""A site that customised a partner doctype's permissions keeps Custom DocPerm rows, and those
	hide the doctype's own rows. Copies the Partner Manager and Staff rows there too, so both roles
	get the same access on every site."""
	customised = frappe.get_all(
		"Custom DocPerm", filters={"parent": ["in", PARTNER_DOCTYPES]}, pluck="parent", distinct=True
	)
	for doctype in customised:
		_copy_staff_rows(doctype)
		frappe.clear_cache(doctype=doctype)


def _copy_staff_rows(doctype):
	frappe.db.delete("Custom DocPerm", {"parent": doctype, "role": ["in", STAFF_ROLES]})
	for row in frappe.get_all("DocPerm", fields="*", filters={"parent": doctype, "role": ["in", STAFF_ROLES]}):
		row.pop("name")
		custom_row = frappe.new_doc("Custom DocPerm")
		custom_row.update(row)
		custom_row.insert(ignore_permissions=True)
