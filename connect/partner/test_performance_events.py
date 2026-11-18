from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from connect.api.partner import submit_partner_review
from connect.customer.doctype.customer_project.customer_project import complete_project, set_hire_reason
from connect.customer.doctype.customer_project.hiring import hire_partner, respond_to_hire
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.partner.sla import mark_overdue_answers_failed

PARTNER = "_Test Events Partner"
ADMIN = "events.partner.admin@example.test"
BUYER = "events.buyer@example.test"


class IntegrationTestPartnerPerformanceEvents(IntegrationTestCase):
	"""The Pulse events behind the Partner Performance dashboard, one per requirement step."""

	def setUp(self):
		from connect.starter_packs.doctype.starter_pack_order.implementation import get_or_open_thread

		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		# Hire emails, notifications and CRM syncs are queued; these tests check events.
		patch("frappe.enqueue").start()
		patch("connect.partner.performance_events.is_recording", return_value=True).start()
		self.capture = patch("connect.partner.performance_events.pulse.capture").start()
		self.addCleanup(patch.stopall)

		make_buyer(BUYER, "Events Buyer Co")
		make_partner(PARTNER)
		make_partner_admin(PARTNER, ADMIN)
		self.project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "Events rollout", "status": "Shared"}
		).insert(ignore_permissions=True)
		self.project.db_set("user", BUYER)
		customer = frappe.db.get_value("Customer Team Member", {"user": BUYER}, "customer")
		self.quote = frappe.get_doc(
			{
				"doctype": "Project Quote",
				"customer_project": self.project.name,
				"partner": PARTNER,
				"thread": get_or_open_thread(customer, PARTNER, BUYER),
			}
		).insert(ignore_permissions=True)

	def as_user(self, user, function, *args):
		frappe.set_user(user)
		try:
			return function(*args)
		finally:
			frappe.set_user("Administrator")

	def sent(self) -> dict[str, list[dict]]:
		"""Each event name with the properties of every time it was sent."""
		events = {}
		for call in self.capture.call_args_list:
			events.setdefault(call.args[0], []).append(call.kwargs["properties"])
		return events

	def quote_it(self):
		self.quote.reload()
		self.quote.update({"status": "Quoted", "amount": 500000, "timeline_weeks": 8})
		self.quote.save(ignore_permissions=True)

	def test_saving_hire_reasons_again_sends_only_the_new_ones(self):
		self.quote_it()
		self.as_user(BUYER, hire_partner, self.quote.name)
		self.as_user(BUYER, set_hire_reason, self.project.name, '["Price"]')
		self.as_user(BUYER, set_hire_reason, self.project.name, '["Price", "Timeline"]')

		reasons = [row["hire_reason"] for row in self.sent()["partner_hire_reason_given"]]
		self.assertEqual(reasons, ["Price", "Timeline"])

	def test_a_hire_reason_outside_the_list_is_rejected(self):
		self.quote_it()
		self.as_user(BUYER, hire_partner, self.quote.name)

		self.assertRaises(
			frappe.ValidationError, self.as_user, BUYER, set_hire_reason, self.project.name, '["Luck"]'
		)
		self.assertFalse(frappe.db.get_value("Customer Project", self.project.name, "hire_reason"))

	def test_a_requirement_s_journey_sends_one_event_per_step(self):
		self.quote_it()
		self.quote.reload()
		self.quote.status = "Interested"
		self.quote.save(ignore_permissions=True)
		self.as_user(BUYER, hire_partner, self.quote.name)
		self.as_user(BUYER, set_hire_reason, self.project.name, '["Timeline", "Price"]', "They knew our industry")
		self.as_user(ADMIN, respond_to_hire, self.quote.name, 1)
		self.as_user(BUYER, complete_project, self.project.name)
		self.as_user(BUYER, submit_partner_review, PARTNER, 5, "Smooth", "Smooth rollout.")

		sent = self.sent()
		self.assertEqual(sent["partner_requirement_answered"][0]["answer"], "Accepted")
		# One event per reason, so the dashboard counts each; the note counts as Other.
		reasons = [row["hire_reason"] for row in sent["partner_hire_reason_given"]]
		self.assertEqual(reasons, ["Price", "Timeline", "Other"])
		review = sent["partner_reviewed"][0]
		self.assertEqual((review["rating"], review["verification"], review["is_hidden"]), (5, "Hired on Connect", 0))
		for event in ("partner_requirement_received", "partner_hired", "partner_project_completed"):
			self.assertEqual(len(sent[event]), 1, event)
		# Interested, then the hire request: both shortlist, and the dashboard counts the requirement once.
		self.assertEqual({row["requirement"] for row in sent["partner_shortlisted"]}, {self.quote.name})

		received = sent["partner_requirement_received"][0]
		self.assertEqual(received["requirement"], self.quote.name)
		self.assertEqual(received["received_on"], self.quote.creation.date().isoformat())
		self.assertEqual((received["partner"], received["partner_country"]), (PARTNER, "India"))

	def test_hiding_a_review_sends_its_new_state(self):
		review = frappe.get_doc(
			{"doctype": "Partner Review", "partner": PARTNER, "reviewer_name": "Old", "rating": 2, "reviewed_on": "2026-11-01"}
		).insert(ignore_permissions=True)
		review.hide("Not about this partner.")

		states = [(row["review"], row["is_hidden"]) for row in self.sent()["partner_reviewed"]]
		self.assertEqual(states, [(review.name, 0), (review.name, 1)])
		self.assertEqual(self.sent()["partner_reviewed"][0]["received_on"], "2026-11-01")

	def test_an_on_time_answer_sends_an_on_time_result(self):
		self.quote_it()
		result = self.sent()["partner_sla_result"]
		self.assertEqual([(row["clock"], row["result"]) for row in result], [("Requirement", "On time")])

	def test_a_timely_decline_is_neutral(self):
		self.quote.reload()
		self.as_user(ADMIN, self.quote.decline_brief)

		sent = self.sent()
		self.assertEqual(sent["partner_requirement_answered"][0]["answer"], "Declined")
		self.assertNotIn("partner_sla_result", sent)

	def test_the_hourly_job_sends_each_miss_once_dated_at_its_deadline(self):
		deadline = now_datetime() - timedelta(hours=2)
		self.quote.db_set({"response_by": deadline, "sla_status": "Due"})

		mark_overdue_answers_failed()
		mark_overdue_answers_failed()

		# Other clocks on the site may be overdue too; count this requirement's misses only.
		misses = [
			call for call in self.capture.call_args_list
			if call.args[0] == "partner_sla_result" and call.kwargs["properties"]["requirement"] == self.quote.name
		]
		self.assertEqual(len(misses), 1)
		self.assertEqual(misses[0].kwargs["properties"]["result"], "Late")
		self.assertEqual(misses[0].kwargs["captured_at"][:16], to_utc_minute(deadline))

	def test_a_chat_reply_before_any_brief_still_counts(self):
		from connect.partner.performance_events import send_chat_reply_result

		reply = frappe.get_doc(
			{"doctype": "Partner Chat Reply", "partner": PARTNER, "thread": self.quote.thread, "status": "Fulfilled", "asked_at": now_datetime()}
		).insert(ignore_permissions=True)
		self.quote.delete(ignore_permissions=True)
		send_chat_reply_result(reply.name, "Fulfilled", now_datetime())

		result = self.sent()["partner_sla_result"][-1]
		self.assertEqual((result["clock"], result["result"], result["requirement"]), ("Chat reply", "On time", None))

	def test_demo_answers_send_nothing(self):
		frappe.flags.simulated_answer = True
		self.addCleanup(setattr, frappe.flags, "simulated_answer", False)
		self.capture.reset_mock()
		self.quote_it()
		self.assertEqual(self.capture.call_count, 0)

	def test_industries_travel_as_one_text(self):
		from connect.partner.performance_events import get_partner_properties

		partner = frappe.get_doc("Partner", PARTNER)
		for industry in ("_Test Events Retail", "_Test Events Food"):
			if not frappe.db.exists("Industry", industry):
				frappe.get_doc({"doctype": "Industry", "title": industry}).insert(ignore_permissions=True)
			partner.append("industries", {"industry": industry})
		partner.save(ignore_permissions=True)

		self.assertEqual(get_partner_properties(PARTNER)["partner_industries"], "_Test Events Retail, _Test Events Food")


def to_utc_minute(at) -> str:
	from connect.partner.performance_events import to_utc_iso

	return to_utc_iso(at)[:16]
