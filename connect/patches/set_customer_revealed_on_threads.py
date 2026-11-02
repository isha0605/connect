import frappe

from connect.customer.doctype.project_quote.project_quote import REVEALING_STATUSES


def execute():
	"""Customers are now anonymous to a partner until they show interest in one of the partner's
	quotes. A thread stays revealed where the partner already had reason to know them: a
	Starter Pack consultant's chat, a chat the customer started themselves, or a quote the
	customer was interested in."""
	Thread = frappe.qb.DocType("Connect Thread")
	frappe.qb.update(Thread).set(Thread.is_customer_revealed, 1).where(Thread.consultant.isnotnull()).run()

	revealed = set(
		frappe.get_all(
			"Project Quote", filters={"status": ["in", REVEALING_STATUSES], "thread": ["is", "set"]}, pluck="thread"
		)
	)
	for thread in frappe.get_all("Connect Thread", filters={"is_customer_revealed": 0}, pluck="name"):
		if thread in revealed or _was_started_by_the_customer(thread):
			frappe.db.set_value("Connect Thread", thread, "is_customer_revealed", 1, update_modified=False)


def _was_started_by_the_customer(thread: str) -> bool:
	"""A thread that didn't start with a brief sent to the partner: the customer contacted them."""
	briefs = set(frappe.get_all("Project Quote", filters={"thread": thread}, pluck="brief_message"))
	first = frappe.get_all("Connect Message", filters={"thread": thread}, order_by="creation asc", limit=1, pluck="name")
	return not briefs or bool(first) and first[0] not in briefs
