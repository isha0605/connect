import frappe

from connect.partner.performance_events import (
	HIRE_CLOCK,
	QUOTE_FIELDS,
	REQUIREMENT_CLOCK,
	SHORTLIST_STATUSES,
	SLA_RESULTS,
	RequirementEvents,
	get_partner_properties,
	hire_reasons,
	send_chat_reply_result,
	send_review_state,
)


def execute():
	"""The Partner Performance dashboard counts Pulse events, which start with this release.
	Sends the steps every requirement already reached, dated at their stored times, so the
	dashboard opens with the history. Pulse stores an event sent twice once."""
	partners = {}
	projects = {
		project.name: project
		for project in frappe.get_all(
			"Customer Project", fields=["name", "status", "hired_quote", "hire_reason", "hire_note", "hired_on", "completed_on"]
		)
	}
	quote_fields = [*QUOTE_FIELDS, "quoted_on", "sla_status", "response_by", "hire_sla_status", "hire_response_by"]
	for quote in frappe.get_all("Project Quote", fields=quote_fields, order_by="creation asc"):
		if quote.partner not in partners:
			partners[quote.partner] = get_partner_properties(quote.partner)
		send_quote_history(RequirementEvents(quote, partners[quote.partner]), projects.get(quote.customer_project))

	for reply in frappe.get_all(
		"Partner Chat Reply", filters={"status": ["in", list(SLA_RESULTS)]}, fields=["name", "status", "replied_at", "reply_by"]
	):
		send_chat_reply_result(reply.name, reply.status, reply.replied_at or reply.reply_by)

	review_fields = ["name", "partner", "customer", "rating", "verification", "is_hidden", "reviewed_on", "creation", "modified"]
	for review in frappe.get_all("Partner Review", fields=review_fields):
		send_review_state(review)


def send_quote_history(events: RequirementEvents, project):
	quote = events.quote
	events.send_received()
	if quote.status != "Awaiting":
		answer = "Declined" if quote.status == "Partner Declined" else "Accepted"
		events.send_answered(answer, quote.answered_on or quote.quoted_on or quote.creation)
	if quote.status in SHORTLIST_STATUSES:
		events.send_shortlisted(quote.quoted_on or quote.creation)
	if quote.sla_status in SLA_RESULTS:
		events.send_sla_result(REQUIREMENT_CLOCK, quote.sla_status, quote.answered_on or quote.response_by)
	if quote.hire_sla_status in SLA_RESULTS:
		events.send_sla_result(HIRE_CLOCK, quote.hire_sla_status, quote.responded_on or quote.hire_response_by)

	if not project or project.hired_quote != quote.name or quote.status != "Hired":
		return
	hired_on = quote.responded_on or project.hired_on or quote.creation
	events.send_hired(hired_on)
	for reason in hire_reasons(project):
		events.send_hire_reason(reason, hired_on)
	if project.status == "Completed":
		events.send_completed(project.completed_on or hired_on)
