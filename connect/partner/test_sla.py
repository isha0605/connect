# Copyright (c) 2026, Isha and contributors
# See license.txt

from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, get_datetime, now_datetime

from connect.api.projects import decline_brief, send_quote
from connect.customer.doctype.customer_project.brief import send_brief
from connect.customer.doctype.customer_project.customer_project import set_quote_status
from connect.customer.doctype.customer_project.demo_quotes import simulate_quotes
from connect.customer.doctype.customer_project.hiring import cancel_hire_request, hire_partner, respond_to_hire
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.messaging.doctype.connect_user_settings.connect_user_settings import WEEKDAYS
from connect.partner.sla import deadline_for, get_answer_deadline, mark_overdue_answers_failed

PARTNER = "_Test SLA Partner"
OWNERLESS_PARTNER = "_Test SLA Ownerless Partner"
SIBLING_PARTNER = "_Test SLA Sibling Partner"
OWNER = "sla.owner@example.test"
SIBLING_OWNER = "sla.sibling.owner@example.test"
ADMIN = "sla.admin@example.test"
BUYER = "sla.buyer@example.test"

# 2026-11-10 is a Tuesday; the 13th a Friday, the 16th a Monday.
TUESDAY_10 = datetime(2026, 11, 10, 10, 0)
WEEKDAY_SCHEDULE = {
	"work_start": "08:00",
	"work_end": "18:00",
	"work_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
}


class TestAnswerDeadline(IntegrationTestCase):
	"""One working day, by the owner's own hours: the deadline math alone."""

	def test_due_the_same_time_next_working_day(self):
		self.assertEqual(deadline_for(TUESDAY_10, WEEKDAY_SCHEDULE), datetime(2026, 11, 11, 10, 0))

	def test_friday_rolls_over_the_weekend(self):
		self.assertEqual(
			deadline_for(datetime(2026, 11, 13, 10, 0), WEEKDAY_SCHEDULE), datetime(2026, 11, 16, 10, 0)
		)

	def test_after_hours_counts_from_the_next_working_morning(self):
		# Friday 20:00 counts from Monday 08:00, so it is due Tuesday 08:00.
		self.assertEqual(
			deadline_for(datetime(2026, 11, 13, 20, 0), WEEKDAY_SCHEDULE), datetime(2026, 11, 17, 8, 0)
		)

	def test_before_hours_counts_from_that_morning(self):
		self.assertEqual(
			deadline_for(datetime(2026, 11, 10, 6, 0), WEEKDAY_SCHEDULE), datetime(2026, 11, 11, 8, 0)
		)

	def test_a_weekend_arrival_counts_from_monday(self):
		self.assertEqual(
			deadline_for(datetime(2026, 11, 14, 12, 0), WEEKDAY_SCHEDULE), datetime(2026, 11, 17, 8, 0)
		)

	def test_a_schedule_without_working_days_still_gets_a_deadline(self):
		schedule = dict(WEEKDAY_SCHEDULE, work_days=[])
		self.assertGreater(deadline_for(TUESDAY_10, schedule), TUESDAY_10)


class SLAFixture(IntegrationTestCase):
	"""A brief sent to a partner with one owner; subclasses drive the clocks."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		# Notification emails and CRM syncs are queued; these tests check the SLA, not them.
		patch("frappe.enqueue").start()
		self.addCleanup(patch.stopall)
		make_partner(PARTNER)
		make_partner_admin(PARTNER, OWNER)
		make_buyer(BUYER, "SLA Buyer Co")
		self.customer = frappe.db.get_value("Customer Team Member", {"user": BUYER}, "customer")
		self.project = self.make_project("Inventory setup")
		self.thread = send_brief(self.project, self.customer, PARTNER)
		self.quote = frappe.db.get_value("Project Quote", {"customer_project": self.project.name}, "name")

	def make_project(self, name):
		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": name, "status": "Shared"}
		).insert(ignore_permissions=True)
		project.db_set("user", BUYER)
		return project

	def sla_row(self):
		return frappe.db.get_value(
			"Project Quote",
			self.quote,
			["sla_status", "response_by", "answered_on", "hire_sla_status", "hire_response_by"],
			as_dict=True,
		)

	def make_overdue(self, field="response_by"):
		frappe.db.set_value(
			"Project Quote", self.quote, field, add_days(now_datetime(), -1), update_modified=False
		)


class IntegrationTestBriefSLA(SLAFixture):
	"""The answer clock on a brief: quoting fulfills, a timely decline is neutral,
	silence fails, and a late decline stays failed."""

	def test_a_new_brief_starts_the_answer_clock(self):
		row = self.sla_row()
		self.assertEqual(row.sla_status, "Due")
		self.assertGreater(row.response_by, now_datetime())
		self.assertIsNone(row.answered_on)

	def test_quoting_in_time_fulfills(self):
		frappe.set_user(OWNER)
		send_quote(self.quote, 400000, 6)

		row = self.sla_row()
		self.assertEqual(row.sla_status, "Fulfilled")
		self.assertIsNotNone(row.answered_on)

	def test_declining_in_time_is_neutral(self):
		frappe.set_user(OWNER)
		decline_brief(self.quote)

		row = self.sla_row()
		self.assertFalse(row.sla_status)
		self.assertIsNotNone(row.answered_on)

	def test_the_hourly_job_fails_silent_briefs(self):
		self.make_overdue()
		mark_overdue_answers_failed()
		self.assertEqual(self.sla_row().sla_status, "Failed")

	def test_a_late_decline_stays_failed(self):
		self.make_overdue()
		mark_overdue_answers_failed()
		frappe.set_user(OWNER)
		decline_brief(self.quote)

		row = self.sla_row()
		self.assertEqual(row.sla_status, "Failed")
		self.assertIsNotNone(row.answered_on)

	def test_the_customers_answer_keeps_the_fulfilled_status(self):
		frappe.set_user(OWNER)
		send_quote(self.quote, 400000, 6)
		frappe.set_user(BUYER)
		set_quote_status(self.quote, "Not Interested", "Price")

		self.assertEqual(self.sla_row().sla_status, "Fulfilled")

	def test_the_deadline_follows_the_owners_working_hours(self):
		set_working_hours(OWNER, "08:00", "18:00", WEEKDAY_SCHEDULE["work_days"])
		self.assertEqual(get_answer_deadline(PARTNER, TUESDAY_10), datetime(2026, 11, 11, 10, 0))

	def test_the_owner_and_admins_take_the_latest_deadline(self):
		set_working_hours(OWNER, "08:00", "18:00", WEEKDAY_SCHEDULE["work_days"])
		make_partner_admin(PARTNER, ADMIN, access="Admin")
		set_working_hours(ADMIN, "09:00", "17:00", ["monday"])

		# The Monday-only Admin's clock starts Monday the 16th, so their deadline is the 23rd.
		self.assertEqual(get_answer_deadline(PARTNER, TUESDAY_10), datetime(2026, 11, 23, 9, 0))

	def test_demo_quotes_earn_no_sla_credit(self):
		frappe.set_user(BUYER)
		simulate_quotes(self.project.name)
		frappe.set_user("Administrator")

		row = self.sla_row()
		self.assertEqual(frappe.db.get_value("Project Quote", self.quote, "status"), "Quoted")
		self.assertFalse(row.sla_status)
		self.assertIsNone(row.answered_on)

	def test_a_partner_without_owners_gets_no_clock_but_answers_are_stamped(self):
		make_partner(OWNERLESS_PARTNER)
		quote = frappe.get_doc(
			{"doctype": "Project Quote", "customer_project": self.project.name, "partner": OWNERLESS_PARTNER}
		).insert(ignore_permissions=True)

		self.assertFalse(quote.sla_status)
		self.assertIsNone(quote.response_by)

		quote.status = "Partner Declined"
		quote.save(ignore_permissions=True)

		self.assertIsNotNone(quote.answered_on)
		self.assertFalse(quote.sla_status)


class IntegrationTestHireSLA(SLAFixture):
	"""The second clock: answering a hire request. A timely decline is neutral, silence
	fails, and a withdrawn request only clears a clock that was still in time."""

	def setUp(self):
		super().setUp()
		frappe.set_user(OWNER)
		send_quote(self.quote, 400000, 6)
		self.hire()

	def hire(self):
		frappe.set_user(BUYER)
		hire_partner(self.quote)
		frappe.set_user("Administrator")

	def answer_hire(self, accept, reason=None):
		frappe.set_user(OWNER)
		respond_to_hire(self.quote, accept, reason)
		frappe.set_user("Administrator")

	def cancel(self):
		frappe.set_user(BUYER)
		cancel_hire_request(self.project.name)
		frappe.set_user("Administrator")

	def test_a_hire_request_starts_its_own_clock(self):
		row = self.sla_row()
		self.assertEqual(row.hire_sla_status, "Due")
		self.assertGreater(row.hire_response_by, now_datetime())
		# The brief clock keeps its own result.
		self.assertEqual(row.sla_status, "Fulfilled")

	def test_accepting_in_time_fulfills(self):
		self.answer_hire(1)
		self.assertEqual(self.sla_row().hire_sla_status, "Fulfilled")

	def test_declining_in_time_is_neutral(self):
		self.answer_hire(0, "Team is fully booked")

		row = self.sla_row()
		self.assertFalse(row.hire_sla_status)
		self.assertIsNotNone(row.hire_response_by)

	def test_the_hourly_job_fails_a_silent_hire_request(self):
		self.make_overdue("hire_response_by")
		mark_overdue_answers_failed()
		self.assertEqual(self.sla_row().hire_sla_status, "Failed")

	def test_a_late_accept_stays_failed(self):
		self.make_overdue("hire_response_by")
		mark_overdue_answers_failed()
		self.answer_hire(1)
		self.assertEqual(self.sla_row().hire_sla_status, "Failed")

	def test_cancelling_in_time_clears_the_clock(self):
		self.cancel()

		row = self.sla_row()
		self.assertFalse(row.hire_sla_status)
		self.assertIsNone(row.hire_response_by)
		self.assertEqual(frappe.db.get_value("Project Quote", self.quote, "status"), "Quoted")

	def test_cancelling_after_the_deadline_keeps_the_miss(self):
		self.make_overdue("hire_response_by")
		self.cancel()
		self.assertEqual(self.sla_row().hire_sla_status, "Failed")

	def test_asking_again_restarts_the_clock(self):
		self.cancel()
		self.hire()

		row = self.sla_row()
		self.assertEqual(row.hire_sla_status, "Due")
		self.assertIsNotNone(row.hire_response_by)

	def test_a_new_request_does_not_erase_a_failed_hire_clock(self):
		self.make_overdue("hire_response_by")
		mark_overdue_answers_failed()
		self.cancel()
		self.hire()
		self.assertEqual(self.sla_row().hire_sla_status, "Failed")

		self.answer_hire(1)
		self.assertEqual(self.sla_row().hire_sla_status, "Failed")

	def send_sibling_brief(self):
		make_partner(SIBLING_PARTNER)
		make_partner_admin(SIBLING_PARTNER, SIBLING_OWNER)
		send_brief(self.project, self.customer, SIBLING_PARTNER)
		return frappe.db.get_value(
			"Project Quote", {"customer_project": self.project.name, "partner": SIBLING_PARTNER}, "name"
		)

	def test_hiring_withdraws_the_other_partners_brief_clocks(self):
		sibling = self.send_sibling_brief()
		self.answer_hire(1)

		row = frappe.db.get_value("Project Quote", sibling, ["sla_status", "response_by"], as_dict=True)
		self.assertFalse(row.sla_status)
		self.assertIsNone(row.response_by)

	def test_hiring_keeps_a_sibling_miss_already_past_its_deadline(self):
		sibling = self.send_sibling_brief()
		frappe.db.set_value(
			"Project Quote", sibling, "response_by", add_days(now_datetime(), -1), update_modified=False
		)
		self.answer_hire(1)

		self.assertEqual(frappe.db.get_value("Project Quote", sibling, "sla_status"), "Failed")


class IntegrationTestChatReplySLA(SLAFixture):
	"""The rolling chat clock: a customer message opens a Due Partner Chat Reply, the
	partner's next message settles it, and silence past one working day fails it."""

	def setUp(self):
		super().setUp()
		# The chat clock stays off while the brief clock runs (one silence, one clock),
		# so the partner answers the brief before each chat scenario.
		frappe.set_user(OWNER)
		send_quote(self.quote, 400000, 6)
		frappe.set_user("Administrator")

	def send_message(self, sender, message_type="Text", content="hello"):
		return frappe.get_doc(
			{
				"doctype": "Connect Message",
				"thread": self.thread,
				"sender": sender,
				"message_type": message_type,
				"content": content,
			}
		).insert(ignore_permissions=True)

	def replies(self):
		return frappe.get_all(
			"Partner Chat Reply",
			filters={"thread": self.thread},
			fields=["status", "partner", "asked_at", "reply_by", "replied_at"],
			order_by="creation asc",
		)

	def statuses(self):
		return [reply.status for reply in self.replies()]

	def make_reply_overdue(self):
		frappe.db.set_value(
			"Partner Chat Reply",
			{"thread": self.thread, "status": "Due"},
			"reply_by",
			add_days(now_datetime(), -1),
			update_modified=False,
		)

	def test_the_requirement_card_leaves_the_chat_clock_alone(self):
		# The brief clock owns that ask; setUp already sent one.
		self.assertEqual(self.statuses(), [])

	def test_a_customer_message_opens_a_dated_clock(self):
		message = self.send_message(BUYER)

		[reply] = self.replies()
		self.assertEqual((reply.status, reply.partner), ("Due", PARTNER))
		self.assertEqual(reply.asked_at, get_datetime(message.creation))
		self.assertGreater(reply.reply_by, now_datetime())

	def test_more_customer_messages_keep_one_clock(self):
		self.send_message(BUYER)
		self.send_message(BUYER)

		self.assertEqual(self.statuses(), ["Due"])

	def test_a_reply_in_time_fulfills(self):
		self.send_message(BUYER)
		self.send_message(OWNER)

		[reply] = self.replies()
		self.assertEqual(reply.status, "Fulfilled")
		self.assertIsNotNone(reply.replied_at)

	def test_each_waiting_turn_is_its_own_record(self):
		self.send_message(BUYER)
		self.send_message(OWNER)
		self.send_message(BUYER)

		self.assertEqual(self.statuses(), ["Fulfilled", "Due"])

	def test_a_late_reply_fails(self):
		self.send_message(BUYER)
		self.make_reply_overdue()
		self.send_message(OWNER)

		self.assertEqual(self.statuses(), ["Failed"])

	def test_the_hourly_job_fails_a_silent_thread_once(self):
		self.send_message(BUYER)
		self.make_reply_overdue()
		mark_overdue_answers_failed()
		self.send_message(OWNER)

		self.assertEqual(self.statuses(), ["Failed"])
		self.assertIsNone(self.replies()[0].replied_at)

	def test_a_system_message_settles_nothing(self):
		self.send_message(BUYER)
		self.send_message(OWNER, message_type="System", content="noted")

		self.assertEqual(self.statuses(), ["Due"])

	def test_no_chat_clock_while_a_brief_awaits_the_partners_answer(self):
		second = self.make_project("Payroll setup")
		send_brief(second, self.customer, PARTNER)
		self.send_message(BUYER)

		self.assertEqual(self.statuses(), [])

	def test_deleting_the_waiting_message_withdraws_the_clock(self):
		message = self.send_message(BUYER)
		frappe.delete_doc("Connect Message", message.name, ignore_permissions=True)

		self.assertEqual(self.statuses(), ["Withdrawn"])

	def test_deleting_one_of_two_waiting_messages_keeps_the_clock(self):
		first = self.send_message(BUYER)
		second = self.send_message(BUYER)
		frappe.delete_doc("Connect Message", second.name, ignore_permissions=True)

		[reply] = self.replies()
		self.assertEqual((reply.status, reply.asked_at), ("Due", get_datetime(first.creation)))

	def test_re_dating_never_reaches_back_past_a_scored_clock(self):
		self.send_message(BUYER)
		self.make_reply_overdue()
		mark_overdue_answers_failed()
		second = self.send_message(BUYER)
		third = self.send_message(BUYER)
		frappe.delete_doc("Connect Message", second.name, ignore_permissions=True)

		replies = self.replies()
		self.assertEqual([reply.status for reply in replies], ["Failed", "Due"])
		self.assertEqual(replies[1].asked_at, get_datetime(third.creation))
		self.assertGreater(replies[1].reply_by, now_datetime())

	def test_deleting_an_older_message_leaves_the_open_clock_alone(self):
		older = self.send_message(BUYER)
		self.send_message(OWNER)
		waiting = self.send_message(BUYER)
		frappe.delete_doc("Connect Message", older.name, ignore_permissions=True)

		replies = self.replies()
		self.assertEqual([reply.status for reply in replies], ["Fulfilled", "Due"])
		self.assertEqual(replies[1].asked_at, get_datetime(waiting.creation))

	def test_a_new_brief_takes_over_an_open_chat_clock(self):
		self.send_message(BUYER)
		second = self.make_project("Payroll setup")
		send_brief(second, self.customer, PARTNER)

		self.assertEqual(self.statuses(), ["Withdrawn"])

	def test_a_new_brief_keeps_a_chat_miss_already_past_its_deadline(self):
		self.send_message(BUYER)
		self.make_reply_overdue()
		second = self.make_project("Payroll setup")
		send_brief(second, self.customer, PARTNER)

		self.assertEqual(self.statuses(), ["Failed"])

	def test_closing_with_a_question_waiting_is_a_miss(self):
		self.send_message(BUYER)
		frappe.get_doc("Connect Thread", self.thread).close(OWNER)

		self.assertEqual(self.statuses(), ["Failed"])

	def test_closing_after_the_partner_answered_counts_nothing_more(self):
		self.send_message(BUYER)
		self.send_message(OWNER)
		frappe.get_doc("Connect Thread", self.thread).close(OWNER)

		self.assertEqual(self.statuses(), ["Fulfilled"])

	def test_closing_past_the_deadline_fails_the_clock(self):
		self.send_message(BUYER)
		self.make_reply_overdue()
		frappe.get_doc("Connect Thread", self.thread).close(OWNER)

		self.assertEqual(self.statuses(), ["Failed"])

	def test_partners_and_customers_cannot_read_chat_replies(self):
		self.send_message(BUYER)
		for user in (OWNER, BUYER):
			frappe.set_user(user)
			self.assertFalse(frappe.has_permission("Partner Chat Reply", "read"))
		frappe.set_user("Administrator")


def set_working_hours(user, start, end, days):
	if frappe.db.exists("Connect User Settings", user):
		doc = frappe.get_doc("Connect User Settings", user)
	else:
		doc = frappe.get_doc({"doctype": "Connect User Settings", "user": user})
	doc.work_start, doc.work_end = start, end
	for day in WEEKDAYS:
		doc.set(day, 1 if day in days else 0)
	doc.save(ignore_permissions=True)
