"""Chat reply SLA: each waiting customer message is one Partner Chat Reply clock."""

import frappe
from frappe.query_builder.functions import Min
from frappe.utils import get_datetime, now_datetime

from connect.partner.sla import get_answer_deadline

REPLY = "Partner Chat Reply"
# Asks the other clocks own: a Requirement card starts the brief clock and a Hire Request
# card the hire clock, so the chat clock skips them to avoid counting one silence twice.
CHAT_CLOCK_SKIPPED_ASKS = ("Requirement", "Hire Request")


def track_thread_reply(message, method=None):
	"""after_insert on Connect Message: a customer message starts the thread's reply clock
	unless one is already running, and the partner's next message settles it."""
	if message.message_type == "System" or frappe.flags.simulated_answer:
		return

	thread = frappe.db.get_value("Connect Thread", message.thread, ["name", "partner", "status"], as_dict=True)
	if not thread or not thread.partner or thread.status != "Open":
		return

	side = _get_sender_side(message.thread, message.sender)
	if side == "Customer":
		_start_clock(thread, message)
	elif side == "Partner":
		_settle_clock(thread.name)


def track_thread_reply_removal(message, method=None):
	"""on_trash on Connect Message: deleting a waiting customer message re-dates the clock
	from the first message still waiting in its window, or withdraws it, so a partner is
	never failed over a question that no longer exists."""
	if message.message_type == "System" or message.message_type in CHAT_CLOCK_SKIPPED_ASKS:
		return

	open_reply = frappe.db.get_value(
		REPLY, {"thread": message.thread, "status": "Due"}, ["name", "partner", "asked_at"], as_dict=True
	)
	# Only a message inside the open clock's own window can change it: anything older was
	# answered, scored by another clock, or never waiting.
	if not open_reply or get_datetime(message.creation) < get_datetime(open_reply.asked_at):
		return
	if _get_sender_side(message.thread, message.sender) != "Customer":
		return

	waiting_since = _first_waiting_customer_message(message, open_reply.asked_at)
	deadline = get_answer_deadline(open_reply.partner, waiting_since) if waiting_since else None
	if not deadline:
		_close_clock(open_reply.name, "Withdrawn")
		return

	frappe.db.set_value(REPLY, open_reply.name, {"asked_at": waiting_since, "reply_by": deadline})


def fail_open_chat_clock(thread: str):
	"""Connect Thread.on_update on close: the partner ended the conversation with the
	customer's question unanswered, so it is a miss even before the deadline."""
	open_reply = frappe.db.get_value(REPLY, {"thread": thread, "status": "Due"}, "name")
	if open_reply:
		_close_clock(open_reply, "Failed")


def _yield_open_chat_clock(thread: str):
	"""A brief or hire clock took over the partner's silence: a chat clock still in time is
	withdrawn, while one already past its deadline is a miss."""
	open_reply = frappe.db.get_value(REPLY, {"thread": thread, "status": "Due"}, ["name", "reply_by"], as_dict=True)
	if not open_reply:
		return

	is_late = now_datetime() > get_datetime(open_reply.reply_by)
	_close_clock(open_reply.name, "Failed" if is_late else "Withdrawn")


def hand_chat_clock_to_quote(quote):
	"""Project Quote.on_update: a brief or hire clock that just started owns the partner's
	silence, so an open chat clock in its thread yields to it (one silence, one clock)."""
	started = any(
		quote.has_value_changed(field) and quote.get(field) == "Due" for field in ("sla_status", "hire_sla_status")
	)
	if started and quote.thread:
		_yield_open_chat_clock(quote.thread)


def _start_clock(thread, message):
	if message.message_type in CHAT_CLOCK_SKIPPED_ASKS:
		return

	# Locks the thread so two customer messages at once open one clock, not two.
	frappe.db.get_value("Connect Thread", thread.name, "name", for_update=True)
	if frappe.db.exists(REPLY, {"thread": thread.name, "status": "Due"}):
		return
	# The partner's silence is already on a brief or hire clock: one silence, one clock.
	if _has_open_quote_clock(thread.name):
		return

	deadline = get_answer_deadline(thread.partner, message.creation)
	if not deadline:
		return

	# A system record: partners and customers have no access to it, admins only read it.
	frappe.get_doc(
		{
			"doctype": REPLY,
			"partner": thread.partner,
			"thread": thread.name,
			"asked_at": message.creation,
			"reply_by": deadline,
			"status": "Due",
		}
	).insert(ignore_permissions=True)


def _settle_clock(thread: str):
	open_reply = frappe.db.get_value(REPLY, {"thread": thread, "status": "Due"}, ["name", "reply_by"], as_dict=True)
	if not open_reply:
		return

	now = now_datetime()
	_close_clock(open_reply.name, "Failed" if now > get_datetime(open_reply.reply_by) else "Fulfilled", replied_at=now)


def _close_clock(name: str, status: str, replied_at=None):
	"""Settles a clock only while it is still Due: the hourly job or a concurrent reply may
	have settled it first, and one silence must count exactly once."""
	Reply = frappe.qb.DocType(REPLY)
	query = frappe.qb.update(Reply).set(Reply.status, status).set(Reply.modified, now_datetime())
	if replied_at:
		query = query.set(Reply.replied_at, replied_at)
	query.where((Reply.name == name) & (Reply.status == "Due")).run()


def _has_open_quote_clock(thread: str) -> bool:
	return bool(
		frappe.db.exists("Project Quote", {"thread": thread, "sla_status": "Due"})
		or frappe.db.exists("Project Quote", {"thread": thread, "hire_sla_status": "Due"})
	)


def _first_waiting_customer_message(deleted_message, since):
	"""When the first customer message still waiting in the clock's window arrived,
	ignoring the one being deleted. No partner message can be in that window: the clock
	would have settled."""
	Message = frappe.qb.DocType("Connect Message")
	Member = frappe.qb.DocType("Connect Thread Member")
	result = (
		frappe.qb.from_(Message)
		.join(Member)
		.on((Member.thread == Message.thread) & (Member.user == Message.sender))
		.select(Min(Message.creation))
		.where(Message.thread == deleted_message.thread)
		.where(Message.name != deleted_message.name)
		.where(Message.creation >= since)
		.where(Message.message_type.notin(("System", *CHAT_CLOCK_SKIPPED_ASKS)))
		.where(Member.side == "Customer")
	).run()
	return result[0][0] if result else None


def _get_sender_side(thread: str, user: str) -> str | None:
	return frappe.db.get_value("Connect Thread Member", {"thread": thread, "user": user, "side": ["is", "set"]}, "side")
