import frappe
from frappe.utils import now_datetime

from connect.partner.doctype.partner.partner import VERIFIED


def execute():
	"""Only approved partners are listed and sent work now. Partners who already work with
	customers on Connect were never approved, as approval didn't gate anything before: approve
	them and an application they sent for review. A rejected partner stays rejected, and a draft
	application stays a draft for them to finish."""
	partners = _active_unapproved_partners()
	if not partners:
		return

	frappe.db.set_value("Partner", {"name": ["in", partners]}, "verification_status", VERIFIED, update_modified=False)
	now = now_datetime()
	for name in frappe.get_all(
		"Partner Application",
		filters={"partner": ["in", partners], "docstatus": 1, "status": "Pending Review"},
		pluck="name",
	):
		frappe.db.set_value(
			"Partner Application",
			name,
			{"status": "Approved", "approved_on": now, "reviewed_on": now},
			update_modified=False,
		)


def _active_unapproved_partners() -> list[str]:
	unapproved = set(
		frappe.get_all(
			"Partner", filters={"verification_status": ["not in", [VERIFIED, "Rejected"]]}, pluck="name"
		)
	) | set(frappe.get_all("Partner", filters={"verification_status": ["is", "not set"]}, pluck="name"))
	if not unapproved:
		return []
	return sorted(_partners_doing_work(list(unapproved)))


def _partners_doing_work(partners: list[str]) -> set[str]:
	"""Partners who did work on Connect: were hired, quoted on a brief, or answered a customer.
	A customer only writing to them, or a brief they never answered, is not work."""
	hired = frappe.get_all("Partner Customer", filters={"partner": ["in", partners]}, pluck="partner", distinct=True)
	quoted = frappe.get_all(
		"Project Quote",
		filters={"partner": ["in", partners], "status": ["!=", "Awaiting"]},
		pluck="partner",
		distinct=True,
	)
	return set(hired) | set(quoted) | _partners_who_replied(partners)


def _partners_who_replied(partners: list[str]) -> set[str]:
	Message = frappe.qb.DocType("Connect Message")
	Thread = frappe.qb.DocType("Connect Thread")
	Member = frappe.qb.DocType("Connect Partner Member")
	rows = (
		frappe.qb.from_(Message)
		.join(Thread)
		.on(Thread.name == Message.thread)
		.join(Member)
		.on((Member.partner == Thread.partner) & (Member.user == Message.sender))
		.select(Thread.partner)
		.distinct()
		.where(Thread.partner.isin(partners))
		.run(pluck=True)
	)
	return set(rows)
