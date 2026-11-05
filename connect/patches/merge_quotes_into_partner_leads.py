import frappe
from frappe.query_builder import Order


def execute():
	"""A partner's lead is now the customer's whole conversation, not each brief in it. Each
	thread's briefs join one Partner Lead, which takes the stage, owner and probability of the
	brief worked last. A thread with a hired brief is Won."""
	if not frappe.db.has_column("Project Quote", "lead_stage"):
		return

	by_thread = {}
	for quote in _quotes_without_lead():
		by_thread.setdefault(quote.thread, []).append(quote)

	for thread, quotes in by_thread.items():
		lead = _make_lead(thread, quotes)
		frappe.db.set_value("Project Quote", {"thread": thread}, "lead", lead, update_modified=False)


def _quotes_without_lead():
	Quote = frappe.qb.DocType("Project Quote")
	Thread = frappe.qb.DocType("Connect Thread")
	return (
		frappe.qb.from_(Quote)
		.join(Thread)
		.on(Thread.name == Quote.thread)
		.select(
			Quote.partner, Quote.thread, Quote.status, Quote.lead_stage, Quote.lead_owner,
			Quote.probability, Quote.lost_reason, Thread.customer,
		)
		.where(Quote.lead.isnull())
		.orderby(Quote.modified, order=Order.desc)
		.run(as_dict=True)
	)


def _make_lead(thread: str, quotes: list) -> str:
	latest = quotes[0]
	stage = "Won" if any(quote.status == "Hired" for quote in quotes) else (latest.lead_stage or "Open")
	lead = frappe.get_doc(
		{
			"doctype": "Partner Lead",
			"partner": latest.partner,
			"customer": latest.customer,
			"thread": thread,
			"stage": stage,
			"assigned_to": latest.lead_owner,
			"probability": latest.probability,
			"lost_reason": latest.lost_reason if stage == "Lost" else None,
		}
	)
	# Copied as the team left them, even an owner who has since lost Sales access or been deleted,
	# and without a new lead's steps: its owner is in the thread and on the CRM Lead already.
	lead.set_new_name()
	lead.set_user_and_timestamp()
	lead.db_insert()
	return lead.name
