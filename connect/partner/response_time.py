from datetime import datetime, timedelta
from itertools import groupby
from statistics import median

import frappe
from frappe.utils import add_days, get_time, now_datetime

from connect.messaging.doctype.connect_user_settings.connect_user_settings import WEEKDAYS, get_settings_for_users

ROLLING_WINDOW_DAYS = 90
MIN_SAMPLES = 3

# Automated notices are posted under a member's name but aren't anyone replying.
SKIPPED_MESSAGE_TYPES = ("System",)


def recompute_all_response_times():
	"""Daily job: stores each partner's median business-hours reply time on Partner.response_time_hours.
	Partners without enough recent replies keep their value, which they can also set on their profile."""
	current = dict(frappe.get_all("Partner", fields=["name", "response_time_hours"], as_list=True))
	for partner, hours in compute_all_response_times().items():
		if hours is not None and hours != current.get(partner):
			frappe.db.set_value("Partner", partner, "response_time_hours", hours, update_modified=False)


def compute_all_response_times() -> dict[str, int | None]:
	"""Each partner's response time in hours over the rolling window, from every thread they're in.
	A sample is the business minutes from a customer's last message to the partner's next reply,
	counted in the replying member's own working hours."""
	messages = _get_recent_messages(add_days(now_datetime(), -ROLLING_WINDOW_DAYS))
	sides = _get_member_sides({message.thread for message in messages})
	schedules = get_settings_for_users([user for (thread, user), side in sides.items() if side == "Partner"])

	samples = {}
	for (partner, thread), thread_messages in groupby(messages, key=lambda m: (m.partner, m.thread)):
		turns = [(sides.get((thread, m.sender)), m.sender, m.creation) for m in thread_messages]
		for asked_at, replier, replied_at in get_replies(turns):
			minutes = get_business_minutes(asked_at, replied_at, schedules[replier])
			samples.setdefault(partner, []).append(minutes)

	return {partner: aggregate_samples(partner_samples) for partner, partner_samples in samples.items()}


def get_replies(turns: list[tuple[str | None, str, datetime]]) -> list[tuple[datetime, str, datetime]]:
	"""(asked_at, replier, replied_at) for each partner reply that follows a customer message, from a
	thread's (side, sender, sent_at) turns in time order. Senders with no side are skipped."""
	replies = []
	asked_at = None
	for side, sender, sent_at in turns:
		if side == "Customer":
			asked_at = sent_at
		elif side == "Partner" and asked_at:
			replies.append((asked_at, sender, sent_at))
			asked_at = None
	return replies


def get_business_minutes(start: datetime, end: datetime, schedule: dict) -> float:
	"""Minutes between `start` and `end` that fall inside the schedule's working hours. Each day's
	work window is clipped to the range, so time after hours or on days off adds nothing."""
	work_start = get_time(schedule["work_start"])
	work_end = get_time(schedule["work_end"])

	total_seconds = 0.0
	day = start.date()
	while day <= end.date():
		if WEEKDAYS[day.weekday()] in schedule["work_days"]:
			window_start = max(datetime.combine(day, work_start), start)
			window_end = min(datetime.combine(day, work_end), end)
			total_seconds += max((window_end - window_start).total_seconds(), 0)
		day += timedelta(days=1)
	return total_seconds / 60


def aggregate_samples(samples: list[float]) -> int | None:
	"""Turn business-minutes samples into the whole hours the badge shows, or None with too few."""
	if len(samples) < MIN_SAMPLES:
		return None
	return max(1, round(median(samples) / 60))


def _get_recent_messages(cutoff: datetime) -> list[dict]:
	"""Messages in partner threads since `cutoff`, grouped by partner and thread, oldest first."""
	Message = frappe.qb.DocType("Connect Message")
	Thread = frappe.qb.DocType("Connect Thread")
	return (
		frappe.qb.from_(Message)
		.join(Thread)
		.on(Thread.name == Message.thread)
		.select(Thread.partner, Message.thread, Message.sender, Message.creation)
		.where(Thread.partner.isnotnull())
		.where(Message.creation >= cutoff)
		.where(Message.message_type.notin(SKIPPED_MESSAGE_TYPES))
		.orderby(Thread.partner)
		.orderby(Message.thread)
		.orderby(Message.creation)
		.run(as_dict=True)
	)


def _get_member_sides(threads: set[str]) -> dict[tuple[str, str], str]:
	"""Which side each member sent from, keyed by (thread, user). Removed members are kept, since
	their past messages still count. Read separately rather than joined, because a re-added
	member has two rows and a join would count their messages twice."""
	if not threads:
		return {}
	members = frappe.get_all(
		"Connect Thread Member",
		filters={"thread": ["in", list(threads)], "side": ["is", "set"]},
		fields=["thread", "user", "side"],
	)
	return {(member.thread, member.user): member.side for member in members}
