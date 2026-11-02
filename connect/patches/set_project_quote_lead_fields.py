import frappe
from frappe.utils import add_to_date


def execute():
	"""Project Quotes became the partner's leads. Each one starts Open, or Won when the
	customer hired the partner, and links the Requirement card that sent the brief."""
	Quote = frappe.qb.DocType("Project Quote")
	(
		frappe.qb.update(Quote)
		.set(Quote.lead_stage, "Open")
		.where(Quote.lead_stage.isnull() | (Quote.lead_stage == ""))
	).run()
	frappe.qb.update(Quote).set(Quote.lead_stage, "Won").where(Quote.status == "Hired").run()

	quotes = frappe.get_all(
		"Project Quote",
		filters={"brief_message": ["is", "not set"], "thread": ["is", "set"]},
		fields=["name", "thread", "customer_project", "creation"],
	)
	for quote in quotes:
		message = _brief_message(quote)
		if message:
			frappe.db.set_value("Project Quote", quote.name, "brief_message", message, update_modified=False)


def _brief_message(quote) -> str | None:
	"""The project owner's latest Requirement card for this project in the thread, sent no
	later than the quote was made."""
	project = frappe.db.get_value("Customer Project", quote.customer_project, ["user", "project_name"], as_dict=True)
	if not project:
		return None
	messages = frappe.get_all(
		"Connect Message",
		filters={
			"thread": quote.thread,
			"sender": project.user,
			"message_type": "Requirement",
			# The card is saved just before its quote; a minute covers a slow request.
			"creation": ["<=", add_to_date(quote.creation, minutes=1)],
		},
		fields=["name", "content"],
		order_by="creation desc",
	)
	for message in messages:
		if (frappe.parse_json(message.content or "{}") or {}).get("project_name") == project.project_name:
			return message.name
	return None
