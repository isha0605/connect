# Copyright (c) 2026, Isha and contributors
# See license.txt

import frappe
from frappe.desk.query_report import run
from frappe.utils import add_days, now_datetime, today

from connect.customer.doctype.customer_project.brief import send_brief
from connect.partner.report.partner_sla_summary.partner_sla_summary import execute
from connect.partner.test_sla import BUYER, OWNER, PARTNER, SLAFixture

REPORT = "Partner SLA Summary"
FILTERS = {"from_date": add_days(today(), -30), "to_date": today(), "partner": PARTNER}


class IntegrationTestPartnerSLASummary(SLAFixture):
	"""The admin-only score: on time ÷ (on time + late), neutral answers left out of both."""

	def make_briefs(self, *statuses):
		"""One brief per status on top of the fixture's own brief: answered now, and a
		Failed one past its deadline, since a brief only fails once its deadline passes."""
		for index, status in enumerate(statuses):
			project = self.make_project(f"Report project {index}")
			send_brief(project, self.customer, PARTNER)
			quote = frappe.db.get_value("Project Quote", {"customer_project": project.name}, "name")
			values = {"sla_status": status, "answered_on": now_datetime()}
			if status == "Failed":
				values["response_by"] = add_days(now_datetime(), -1)
			frappe.db.set_value("Project Quote", quote, values)

	def partner_row(self):
		rows = execute(FILTERS)[1]
		return next((row for row in rows if row["partner"] == PARTNER), None)

	def test_the_score_is_on_time_over_scored_answers(self):
		self.make_briefs("Fulfilled", "Fulfilled", "Failed")

		row = self.partner_row()
		self.assertEqual((row["brief_on_time"], row["brief_late"]), (2, 1))
		self.assertEqual(row["sla_score"], 66.7)
		self.assertFalse(row["is_new"])

	def test_timely_declines_and_running_clocks_count_in_neither_column(self):
		# "" is a timely decline; the fixture's own brief is still Due.
		self.make_briefs("Fulfilled", "Fulfilled", "Failed", "", "")

		row = self.partner_row()
		self.assertEqual((row["total_on_time"], row["total_late"]), (2, 1))
		self.assertEqual(row["sla_score"], 66.7)

	def test_too_few_answers_shows_new_instead_of_a_score(self):
		self.make_briefs("Fulfilled", "Fulfilled")

		row = self.partner_row()
		self.assertTrue(row["is_new"])
		self.assertIsNone(row["sla_score"])

	def test_answers_outside_the_dates_are_left_out(self):
		self.make_briefs("Fulfilled", "Fulfilled", "Failed")
		frappe.db.set_value(
			"Project Quote",
			{"partner": PARTNER, "sla_status": "Failed"},
			"response_by",
			add_days(now_datetime(), -60),
		)

		row = self.partner_row()
		self.assertEqual((row["brief_on_time"], row["brief_late"]), (2, 0))

	def test_an_answer_late_on_the_to_date_is_included(self):
		self.make_briefs("Fulfilled", "Fulfilled", "Failed")
		late_tonight = now_datetime().replace(hour=23, minute=30)
		frappe.db.set_value(
			"Project Quote", {"partner": PARTNER, "sla_status": "Fulfilled"}, "answered_on", late_tonight
		)

		self.assertEqual(self.partner_row()["brief_on_time"], 2)

	def test_a_miss_stays_in_the_period_of_its_deadline(self):
		self.make_briefs("Fulfilled", "Fulfilled", "Failed")
		# Due 60 days ago and failed then; the late answer only arrives today.
		frappe.db.set_value(
			"Project Quote",
			{"partner": PARTNER, "sla_status": "Failed"},
			{"response_by": add_days(now_datetime(), -60), "answered_on": now_datetime()},
		)

		self.assertEqual(self.partner_row()["brief_late"], 0)

	def make_chat_replies(self, *statuses, days_ago=0):
		"""Settled chat clocks on the fixture's thread, answered or due `days_ago`."""
		when = add_days(now_datetime(), -days_ago)
		for status in statuses:
			frappe.get_doc(
				{
					"doctype": "Partner Chat Reply",
					"partner": PARTNER,
					"thread": self.thread,
					"status": status,
					"asked_at": add_days(when, -1),
					"reply_by": when,
					"replied_at": when if status == "Fulfilled" else None,
				}
			).insert(ignore_permissions=True)

	def test_chat_replies_follow_the_date_filter(self):
		self.make_chat_replies("Fulfilled", "Failed")
		self.make_chat_replies("Failed", "Failed", days_ago=60)

		row = self.partner_row()
		self.assertEqual((row["chat_on_time"], row["chat_late"]), (1, 1))

	def test_withdrawn_chat_replies_count_in_neither_column(self):
		self.make_chat_replies("Fulfilled", "Withdrawn", "Due")

		row = self.partner_row()
		self.assertEqual((row["chat_on_time"], row["chat_late"]), (1, 0))

	def test_missing_or_swapped_dates_are_refused(self):
		self.assertRaises(frappe.ValidationError, execute, {"partner": PARTNER})
		swapped = {**FILTERS, "from_date": today(), "to_date": add_days(today(), -1)}
		self.assertRaises(frappe.ValidationError, execute, swapped)

	def test_chat_and_hire_answers_add_to_the_score(self):
		self.make_briefs("Fulfilled")
		self.make_chat_replies("Fulfilled", "Fulfilled", "Fulfilled", "Failed")
		frappe.db.set_value(
			"Project Quote", self.quote, {"hire_sla_status": "Fulfilled", "responded_on": now_datetime()}
		)

		row = self.partner_row()
		self.assertEqual((row["chat_on_time"], row["chat_late"], row["hire_on_time"]), (3, 1, 1))
		self.assertEqual((row["total_on_time"], row["total_late"]), (5, 1))

	def test_partners_and_customers_cannot_run_the_report(self):
		for user in (OWNER, BUYER):
			frappe.set_user(user)
			self.assertRaises(frappe.PermissionError, run, REPORT, filters=FILTERS)
		frappe.set_user("Administrator")

	def test_a_system_manager_can_run_the_report(self):
		self.make_briefs("Fulfilled", "Fulfilled", "Failed")

		result = run(REPORT, filters=FILTERS)
		self.assertTrue(any(row["partner"] == PARTNER for row in result["result"]))
