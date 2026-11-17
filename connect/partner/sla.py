"""Answer SLAs on Project Quote: one working day to answer a brief or a hire request."""

from datetime import date, datetime, timedelta

import frappe
from frappe.utils import get_datetime, get_time, now_datetime

from connect.messaging.doctype.connect_user_settings.connect_user_settings import (
	WEEKDAYS,
	get_settings_for_users,
)
from connect.partner.performance_events import (
	HIRE_CLOCK,
	QUOTE_FIELDS,
	REQUIREMENT_CLOCK,
	send_chat_reply_result,
	send_overdue_results,
)

ANSWER_STATUSES = ("Quoted", "Partner Declined")
# Guards the calendar walk when a schedule has no working day at all (odd or stale data).
MAX_LOOKAHEAD_DAYS = 14


def assign_answer_deadline(quote):
	"""Starts the answer clock when a brief reaches a partner (Project Quote.before_insert)."""
	deadline = get_answer_deadline(quote.partner, now_datetime())
	if not deadline:
		return

	quote.response_by = deadline
	quote.sla_status = "Due"


def record_answer(quote):
	"""Keeps both clocks on a status change (Project Quote.validate): the partner's first
	answer to the brief, and their answer to a hire request.

	A timely decline clears the clock instead of fulfilling it, so saying no neither helps
	nor hurts the score. A late answer of either kind is Failed, so declining after the
	deadline does not erase a miss."""
	previous = quote.get_doc_before_save()

	if quote.status == "Hire Requested":
		_start_hire_answer_clock(quote)
	elif previous and previous.status == "Hire Requested":
		_settle_hire_answer(quote)
	else:
		_settle_brief_answer(quote)


def _settle_brief_answer(quote):
	if quote.status not in ANSWER_STATUSES or quote.answered_on:
		return

	if frappe.flags.simulated_answer:
		# A demo answered for the partner, so nobody earns or loses anything.
		quote.sla_status = ""
		return

	# The answer is stamped even without a clock (a partner without owners gets none).
	quote.answered_on = now_datetime()
	if not quote.response_by:
		return

	if quote.answered_on > get_datetime(quote.response_by):
		quote.sla_status = "Failed"
	else:
		quote.sla_status = "Fulfilled" if quote.status == "Quoted" else ""


def _start_hire_answer_clock(quote):
	"""A fresh clock per request: the customer can cancel and ask the same partner again.
	A recorded miss stays, though: a new request never overwrites a Failed clock."""
	if quote.hire_sla_status == "Failed":
		return

	deadline = get_answer_deadline(quote.partner, now_datetime())
	if not deadline:
		return

	quote.hire_response_by = deadline
	quote.hire_sla_status = "Due"


def _settle_hire_answer(quote):
	"""The request was accepted, declined, cancelled, or expired. A clock the hourly job
	already failed stays Failed. A withdrawn request (cancel or expiry) clears a clock
	still in time: the ask was taken back, not missed."""
	if quote.hire_sla_status != "Due" or not quote.hire_response_by:
		return

	if now_datetime() > get_datetime(quote.hire_response_by):
		quote.hire_sla_status = "Failed"
	elif quote.status == "Hired":
		quote.hire_sla_status = "Fulfilled"
	elif quote.status == "Hire Declined":
		quote.hire_sla_status = ""
	else:
		quote.hire_sla_status = ""
		quote.hire_response_by = None


def mark_overdue_answers_failed():
	"""Hourly job: an unanswered ask past its deadline — brief, hire request, or chat
	message — fails, so a partner's silence shows up without anyone saving the record."""
	now = now_datetime()
	Quote = frappe.qb.DocType("Project Quote")
	_fail_quote_clocks(REQUIREMENT_CLOCK, Quote.sla_status, Quote.response_by, Quote.response_by < now)
	_fail_quote_clocks(HIRE_CLOCK, Quote.hire_sla_status, Quote.hire_response_by, Quote.hire_response_by < now)

	Reply = frappe.qb.DocType("Partner Chat Reply")
	overdue = (Reply.status == "Due") & (Reply.reply_by < now)
	replies = frappe.qb.from_(Reply).select(Reply.name, Reply.reply_by).where(overdue).for_update().run(as_dict=True)
	if not replies:
		return

	# Bumping modified makes a stale open copy fail its save instead of reverting the miss.
	(
		frappe.qb.update(Reply)
		.set(Reply.status, "Failed")
		.set(Reply.modified, now)
		.where(overdue & Reply.name.isin([reply.name for reply in replies]))
	).run()
	for reply in replies:
		send_chat_reply_result(reply.name, "Failed", reply.reply_by)


def withdraw_sibling_brief_clocks(hired_quote):
	"""The project found its partner, so the other partners' unanswered briefs are withdrawn:
	a clock still in time is cleared, while one past its deadline failed when the project was
	still open, so that miss stays."""
	now = now_datetime()
	Quote = frappe.qb.DocType("Project Quote")
	siblings = (
		(Quote.customer_project == hired_quote.customer_project)
		& (Quote.name != hired_quote.name)
		& (Quote.sla_status == "Due")
	)

	_fail_quote_clocks(REQUIREMENT_CLOCK, Quote.sla_status, Quote.response_by, siblings & (Quote.response_by < now))
	(
		frappe.qb.update(Quote)
		.set(Quote.sla_status, "")
		.set(Quote.response_by, None)
		.set(Quote.modified, now)
		.where(siblings & (Quote.response_by >= now))
	).run()


def _fail_quote_clocks(clock: str, status, deadline, overdue):
	"""Fails every Due clock matching `overdue` in one update. The rows are locked first, so
	an answer saved meanwhile waits, and each miss is sent to Pulse exactly as stored."""
	Quote = frappe.qb.DocType("Project Quote")
	condition = (status == "Due") & overdue
	fields = [getattr(Quote, field) for field in QUOTE_FIELDS]
	quotes = frappe.qb.from_(Quote).select(*fields, deadline.as_("deadline")).where(condition).for_update().run(as_dict=True)
	if not quotes:
		return

	# Bumping modified makes a stale open copy fail its save instead of reverting the miss.
	(
		frappe.qb.update(Quote)
		.set(status, "Failed")
		.set(Quote.modified, now_datetime())
		.where(condition & Quote.name.isin([quote.name for quote in quotes]))
	).run()
	send_overdue_results(clock, quotes)


def get_answer_deadline(partner: str, arrival: datetime) -> datetime | None:
	"""When the partner's answer to a brief arriving at `arrival` is due: the latest owner's
	next-working-day deadline, so the firm fails only once every owner's calendar is past it."""
	from connect.permissions import _get_partner_owners

	owners = _get_partner_owners(partner)
	if not owners:
		return None

	# A fresh document's creation can still be a string inside its own after_insert.
	arrival = get_datetime(arrival)
	schedules = get_settings_for_users(owners)
	return max(deadline_for(arrival, schedules[owner]) for owner in owners)


def deadline_for(arrival: datetime, schedule: dict) -> datetime:
	"""Same time on the next working day. An off-hours arrival counts from the next working
	moment first, so evenings and days off never shorten the answer window."""
	start = _next_working_moment(arrival, schedule)
	return datetime.combine(_next_working_date(start.date(), schedule), start.time())


def _next_working_moment(moment: datetime, schedule: dict) -> datetime:
	if _is_working_day(moment.date(), schedule):
		work_start = get_time(schedule["work_start"])
		if moment.time() < work_start:
			return datetime.combine(moment.date(), work_start)
		if moment.time() < get_time(schedule["work_end"]):
			return moment

	next_day = _next_working_date(moment.date(), schedule)
	return datetime.combine(next_day, get_time(schedule["work_start"]))


def _next_working_date(after: date, schedule: dict) -> date:
	day = after
	for _step in range(MAX_LOOKAHEAD_DAYS):
		day += timedelta(days=1)
		if _is_working_day(day, schedule):
			return day

	# No working day in the schedule: fall back to tomorrow rather than walk forever.
	return after + timedelta(days=1)


def _is_working_day(day: date, schedule: dict) -> bool:
	return WEEKDAYS[day.weekday()] in schedule["work_days"]
