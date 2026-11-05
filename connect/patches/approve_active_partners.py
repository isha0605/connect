import frappe
from frappe.utils import now_datetime

from connect.partner.doctype.partner.partner import VERIFIED

# Records that show a partner already works with customers on Connect.
ACTIVITY_DOCTYPES = ("Partner Lead", "Project Quote", "Partner Customer", "Connect Thread")


def execute():
	"""Only approved partners are listed and sent work now. Partners who already work with
	customers on Connect were never approved, as approval didn't gate anything before: approve
	them and their open application. A rejected partner stays rejected."""
	partners = _active_unapproved_partners()
	if not partners:
		return

	frappe.db.set_value("Partner", {"name": ["in", partners]}, "verification_status", VERIFIED, update_modified=False)
	now = now_datetime()
	for name in frappe.get_all(
		"Partner Application",
		filters={"partner": ["in", partners], "status": ["in", ["Draft", "Pending Review"]]},
		pluck="name",
	):
		frappe.db.set_value(
			"Partner Application",
			name,
			{"docstatus": 1, "status": "Approved", "approved_on": now, "reviewed_on": now},
			update_modified=False,
		)


def _active_unapproved_partners() -> list[str]:
	unapproved = set(
		frappe.get_all(
			"Partner", filters={"verification_status": ["not in", [VERIFIED, "Rejected"]]}, pluck="name"
		)
	) | set(frappe.get_all("Partner", filters={"verification_status": ["is", "not set"]}, pluck="name"))
	active = set()
	for doctype in ACTIVITY_DOCTYPES:
		active.update(frappe.get_all(doctype, filters={"partner": ["in", list(unapproved) or [""]]}, pluck="partner", distinct=True))
	return sorted(active & unapproved)
