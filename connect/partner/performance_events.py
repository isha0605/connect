from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_datetime, get_system_timezone, getdate, now_datetime
from frappe.utils.telemetry.pulse import client as pulse

from connect.analytics import APP, get_team, team_id

RECEIVED = "partner_requirement_received"
ANSWERED = "partner_requirement_answered"
SHORTLISTED = "partner_shortlisted"
HIRED = "partner_hired"
HIRE_REASON = "partner_hire_reason_given"
COMPLETED = "partner_project_completed"
SLA_RESULT = "partner_sla_result"
REVIEWED = "partner_reviewed"

REQUIREMENT_CLOCK = "Requirement"
HIRE_CLOCK = "Hire request"
CHAT_CLOCK = "Chat reply"
SLA_RESULTS = {"Fulfilled": "On time", "Failed": "Late"}
ANSWERS = {"Quoted": "Accepted", "Partner Declined": "Declined"}
# Pulse refuses an event captured over 30 days ago. The dashboard dates by `received_on`,
# so an older step (the history patch) is sent as of the oldest time Pulse accepts.
OLDEST_ACCEPTED_AGE = timedelta(days=29)
# The customer showed interest in the quote: every step after Interested passed through it.
SHORTLIST_STATUSES = ("Interested", "Hire Requested", "Hired", "Hire Declined")
# The steps that shortlist live: a hire can be requested straight from a quote. The
# dashboard counts requirements, so a second shortlist of the same one counts once.
SHORTLISTING_STATUSES = ("Interested", "Hire Requested")


class RequirementEvents:
	"""The Partner Performance dashboard's events for one requirement (a Project Quote),
	sent to Pulse like the customer journey's. Each carries the partner's country, tier and
	industries, and when the requirement was received, which the dashboard dates by.

	`captured_at` is always a stored time, never "now" when one exists, so an event sent
	twice (a retry, or the history patch meeting a live event) is the same event, and Pulse
	stores it once."""

	def __init__(self, quote, partner: dict | None = None, team: str | None = None):
		self.quote = quote
		# Read only when an event is sent: most quote saves send nothing.
		self.partner = partner
		self.team = team

	def send_quote_steps(self):
		"""Project Quote.on_update: one event for each step this save reached."""
		quote, now = self.quote, now_datetime()
		if quote.has_value_changed("status"):
			self._send_status_step(now)

		settled_at = {REQUIREMENT_CLOCK: quote.answered_on or now, HIRE_CLOCK: quote.responded_on or now}
		for clock, field in ((REQUIREMENT_CLOCK, "sla_status"), (HIRE_CLOCK, "hire_sla_status")):
			if quote.has_value_changed(field) and quote.get(field) in SLA_RESULTS:
				self.send_sla_result(clock, quote.get(field), settled_at[clock])

	def send_received(self):
		self.send(RECEIVED, self.quote.creation)

	def send_answered(self, answer: str, at):
		self.send(ANSWERED, at, {"answer": answer})

	def send_shortlisted(self, at):
		self.send(SHORTLISTED, at)

	def send_hired(self, at):
		days = (get_datetime(at) - get_datetime(self.quote.creation)).total_seconds() / 86400
		self.send(HIRED, at, {"days_to_customer": round(days, 1)})

	def send_hire_reason(self, reason: str, at):
		self.send(HIRE_REASON, at, {"hire_reason": reason})

	def send_completed(self, at):
		self.send(COMPLETED, at)

	def send_sla_result(self, clock: str, status: str, at, received_on=None, clock_id: str | None = None):
		# One result per clock: the dashboard counts distinct clocks, so a resent result counts once.
		clock_id = clock_id or f"{self.quote.name}:{clock}"
		self.send(SLA_RESULT, at, {"clock": clock, "clock_id": clock_id, "result": SLA_RESULTS[status]}, received_on)

	def send_reviewed(self, review, at):
		self.send(
			REVIEWED,
			at,
			{
				"review": review.name,
				"rating": review.rating,
				"verification": review.verification or "",
				"is_hidden": int(bool(review.is_hidden)),
			},
		)

	def send(self, event: str, at, properties: dict | None = None, received_on=None):
		# A demo answered for the partner; it must not reach the real numbers.
		if frappe.flags.simulated_answer or not is_recording():
			return

		self.partner = self.partner or get_partner_properties(self.quote.partner)
		customer_user = self.quote.customer_project and frappe.db.get_value(
			"Customer Project", self.quote.customer_project, "user"
		)
		properties = {
			**self.partner,
			**(properties or {}),
			"requirement": self.quote.name,
			"received_on": getdate(received_on or self.quote.creation).isoformat(),
		}
		pulse.capture(
			event,
			APP,
			user=customer_user or "Guest",
			team=get_team(customer_user) if customer_user else self.team,
			captured_at=to_utc_iso(max(get_datetime(at), now_datetime() - OLDEST_ACCEPTED_AGE)),
			properties=properties,
		)

	def _send_status_step(self, now):
		status = self.quote.status
		if status in ANSWERS:
			self.send_answered(ANSWERS[status], self.quote.answered_on or now)
		elif status in SHORTLISTING_STATUSES:
			self.send_shortlisted(now)
		elif status == "Hired":
			self.send_hired(self.quote.responded_on or now)


def send_project_events(project):
	"""Customer Project.on_update: its hire's completion, and why the customer chose them."""
	if not project.hired_quote:
		return

	if project.status == "Completed" and project.has_value_changed("status"):
		RequirementEvents(get_quote(project.hired_quote)).send_completed(project.completed_on or now_datetime())
	if project.has_value_changed("hire_reason") or project.has_value_changed("hire_note"):
		before = project.get_doc_before_save()
		already_sent = set(hire_reasons(before)) if before else set()
		events = RequirementEvents(get_quote(project.hired_quote))
		for reason in hire_reasons(project):
			if reason not in already_sent:
				events.send_hire_reason(reason, now_datetime())


def hire_reasons(project) -> list[str]:
	"""One reason per event, so the dashboard counts each; a written note counts as Other."""
	reasons = (project.hire_reason or "").splitlines()
	return reasons + ["Other"] if project.hire_note else reasons


def send_review_event(review):
	"""Partner Review.on_update: the review's current state, whenever its rating, standing or
	visibility changes. The dashboard reads each review's latest event, so an edit or a hide
	replaces what it counted."""
	if any(review.has_value_changed(field) for field in REVIEW_FIELDS):
		send_review_state(review)


def send_review_state(review):
	"""A review isn't one requirement's: a past customer reviews from a request, with none. It is
	dated by the day it was written."""
	written = frappe._dict(
		name=None, partner=review.partner, customer_project=None, creation=review.reviewed_on or review.creation
	)
	team = team_id(review.customer) if review.customer else None
	RequirementEvents(written, team=team).send_reviewed(review, review.modified)


def send_chat_reply_result(reply_name: str, status: str, at):
	"""A chat reply clock settled On time or Late. Its requirement is the thread's newest
	brief; a chat before any brief is still the partner's reply, with no requirement."""
	reply = frappe.db.get_value("Partner Chat Reply", reply_name, ["thread", "partner", "asked_at"], as_dict=True)
	quote = frappe.db.get_value(
		"Project Quote", {"thread": reply.thread}, QUOTE_FIELDS, as_dict=True, order_by="creation desc"
	)
	if quote:
		events = RequirementEvents(quote)
	else:
		customer = frappe.db.get_value("Connect Thread", reply.thread, "customer")
		no_brief = frappe._dict(name=None, partner=reply.partner, customer_project=None, creation=reply.asked_at)
		events = RequirementEvents(no_brief, team=team_id(customer) if customer else None)
	events.send_sla_result(CHAT_CLOCK, status, at, received_on=reply.asked_at, clock_id=reply_name)


def send_overdue_results(clock: str, quotes: list[dict]):
	"""Clocks failed in one update, which no controller saw. A miss is dated at its deadline."""
	for quote in quotes:
		RequirementEvents(quote).send_sla_result(clock, "Failed", quote.deadline)


REVIEW_FIELDS = ("rating", "verification", "is_hidden")
QUOTE_FIELDS = ["name", "partner", "customer_project", "creation", "status", "answered_on", "responded_on"]


def get_quote(name: str) -> dict:
	return frappe.db.get_value("Project Quote", name, QUOTE_FIELDS, as_dict=True)


def get_partner_properties(partner: str) -> dict:
	"""What the dashboard filters by. Industries are one text, so a filter on one industry
	matches with "contains" and a partner in several is still counted once."""
	values = frappe.db.get_value("Partner", partner, ["partner_name", "country", "tier"], as_dict=True) or {}
	industries = frappe.get_all("Partner Industry", filters={"parent": partner}, pluck="industry", order_by="idx")
	return {
		"partner": partner,
		"partner_name": values.get("partner_name") or partner,
		"partner_country": values.get("country") or "",
		"partner_tier": values.get("tier") or "",
		"partner_industries": ", ".join(industries),
	}


def is_recording() -> bool:
	# Test runs share the site, and their made-up partners must not reach the real numbers.
	return not frappe.flags.in_test and pulse.is_enabled()


def to_utc_iso(at) -> str:
	"""Connect stores times in the system timezone; Pulse expects UTC."""
	local = get_datetime(at).replace(tzinfo=ZoneInfo(get_system_timezone()))
	return local.astimezone(UTC).isoformat()
