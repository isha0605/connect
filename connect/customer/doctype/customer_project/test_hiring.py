# Copyright (c) 2026
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime

from connect.customer.doctype.customer_project.customer_project import get_project, set_quote_status
from connect.customer.doctype.customer_project.hiring import (
	HIRE_REQUEST_EXPIRY_DAYS,
	cancel_hire_request,
	expire_hire_requests,
	hire_partner,
	hire_request_statuses,
	respond_to_hire,
)

PARTNER = "_Test Hiring Partner"
BUYER = "hiring.buyer@example.test"
PARTNER_ADMIN = "hiring.partner.admin@example.test"


def make_partner(partner_name):
	if not frappe.db.exists("Partner", partner_name):
		tier = next(t for t in frappe.get_meta("Partner").get_field("tier").options.split("\n") if t)
		frappe.get_doc(
			{"doctype": "Partner", "partner_name": partner_name, "tier": tier, "country": "India"}
		).insert(ignore_permissions=True)
	return partner_name


def make_buyer(email, company):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Buyer"}).insert(
			ignore_permissions=True
		)
	if not frappe.db.exists("Customer", company):
		frappe.get_doc({"doctype": "Customer", "customer_name": company}).insert(ignore_permissions=True)
	if not frappe.db.exists("Customer Team Member", {"user": email}):
		frappe.get_doc({"doctype": "Customer Team Member", "customer": company, "user": email}).insert(
			ignore_permissions=True
		)
	return email


def make_partner_admin(partner, email):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Admin"}).insert(
			ignore_permissions=True
		)
	if not frappe.db.exists("Connect Partner Member", {"partner": partner, "user": email}):
		frappe.get_doc(
			{"doctype": "Connect Partner Member", "partner": partner, "user": email, "is_admin": 1}
		).insert(ignore_permissions=True)
	return email


# The email goes out in a background job; these tests check the request, not the mail.
@patch("connect.customer.doctype.customer_project.hiring.frappe.enqueue")
class TestHiring(IntegrationTestCase):
	def setUp(self):
		from connect.starter_packs.doctype.starter_pack_order.implementation import get_or_open_thread

		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		# The expiry job commits per project; a test's records must still roll back.
		patch("connect.customer.doctype.customer_project.hiring.frappe.db.commit").start()
		self.addCleanup(patch.stopall)
		make_partner(PARTNER)
		make_partner_admin(PARTNER, PARTNER_ADMIN)
		make_buyer(BUYER, "Hiring Buyer Co")
		customer = frappe.db.get_value("Customer Team Member", {"user": BUYER}, "customer")

		self.project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "ERP rollout", "status": "Shared", "user": BUYER}
		).insert(ignore_permissions=True)
		self.project.db_set("user", BUYER)
		thread = get_or_open_thread(customer, PARTNER, BUYER)
		self.quote = frappe.get_doc(
			{
				"doctype": "Project Quote",
				"customer_project": self.project.name,
				"partner": PARTNER,
				"thread": thread,
				"status": "Interested",
				"amount": 875000,
				"timeline_weeks": 8,
			}
		).insert(ignore_permissions=True)
		frappe.set_user(BUYER)

	def request(self):
		frappe.set_user(BUYER)
		return hire_partner(self.quote.name)

	def answer(self, accept, reason=None, user=PARTNER_ADMIN):
		frappe.set_user(user)
		return respond_to_hire(self.quote.name, accept, reason)

	def states(self):
		return (
			frappe.db.get_value("Customer Project", self.project.name, "status"),
			frappe.db.get_value("Project Quote", self.quote.name, "status"),
		)

	def test_hiring_asks_the_partner_and_waits(self, enqueue):
		project = self.request()
		self.assertEqual(self.states(), ("Hiring", "Hire Requested"))
		self.assertFalse(project["hired"]["confirmed"])
		self.assertIsNone(project["hired"]["central_setup_url"])
		self.assertFalse(frappe.db.get_value("Customer Project", self.project.name, "cloud_link_status"))

		card = frappe.get_all(
			"Connect Message",
			filters={"thread": self.quote.thread, "message_type": "Hire Request"},
			pluck="content",
		)
		self.assertEqual(frappe.parse_json(card[0])["quote"], self.quote.name)
		self.assertEqual(enqueue.call_args.kwargs["admin"], PARTNER_ADMIN)

	def test_the_partners_bell_names_the_project(self, enqueue):
		self.request()
		subjects = [call.kwargs["doc"]["subject"] for call in enqueue.call_args_list if "doc" in call.kwargs]
		self.assertIn("Hire request: ERP rollout", subjects)

	def test_the_partner_accepting_makes_them_the_projects_partner(self, enqueue):
		self.request()
		self.answer(accept=1)
		self.assertEqual(self.states(), ("Hired", "Hired"))
		self.assertEqual(
			frappe.db.get_value("Customer Project", self.project.name, "cloud_link_status"), "Pending"
		)
		frappe.set_user(BUYER)
		self.assertTrue(get_project(self.project.name)["hired"]["confirmed"])

	def test_declining_needs_a_reason_and_frees_the_project(self, enqueue):
		self.request()
		with self.assertRaises(frappe.ValidationError):
			self.answer(accept=0, reason=" ")
		self.answer(accept=0, reason="We're fully booked until March.")

		self.assertEqual(self.states(), ("Shared", "Hire Declined"))
		frappe.set_user(BUYER)
		project = get_project(self.project.name)
		self.assertIsNone(project["hired"])
		self.assertEqual(
			project["declined_hire"], {"partner_name": PARTNER, "reason": "We're fully booked until March."}
		)

	def hire_cards(self):
		return frappe.get_all(
			"Connect Message",
			filters={
				"thread": self.quote.thread,
				"message_type": "Hire Request",
				"content": ["like", f'%"{self.quote.name}"%'],
			},
			pluck="name",
			order_by="creation asc",
		)

	def test_the_card_shows_who_can_still_answer(self, enqueue):
		self.request()
		(card,) = self.hire_cards()
		frappe.set_user(PARTNER_ADMIN)
		self.assertTrue(hire_request_statuses(self.quote.thread)[card]["can_answer"])
		frappe.set_user(BUYER)
		self.assertEqual(
			hire_request_statuses(self.quote.thread)[card],
			{"status": "Hire Requested", "decline_reason": None, "can_answer": False},
		)

	def test_asking_again_leaves_the_older_card_withdrawn(self, enqueue):
		self.request()
		cancel_hire_request(self.project.name)
		self.request()
		self.answer(accept=1)
		older, newer = self.hire_cards()
		statuses = hire_request_statuses(self.quote.thread)
		self.assertEqual((statuses[older]["status"], statuses[newer]["status"]), ("Withdrawn", "Hired"))

	def test_outsiders_cant_read_a_threads_hire_requests(self, enqueue):
		outsider = make_buyer("hiring.outsider@example.test", "Outsider Co")
		frappe.set_user(outsider)
		with self.assertRaises(frappe.PermissionError):
			hire_request_statuses(self.quote.thread)

	def test_only_the_partners_admin_can_answer(self, enqueue):
		self.request()
		with self.assertRaises(frappe.PermissionError):
			self.answer(accept=1, user=BUYER)

	def test_an_answered_request_cant_be_answered_again(self, enqueue):
		self.request()
		self.answer(accept=1)
		with self.assertRaises(frappe.ValidationError):
			self.answer(accept=0, reason="Changed our mind")

	def test_cancelling_puts_the_quote_back_where_it_was(self, enqueue):
		self.request()
		cancel_hire_request(self.project.name)
		self.assertEqual(self.states(), ("Shared", "Interested"))
		with self.assertRaises(frappe.ValidationError):
			self.answer(accept=1)

	def test_only_the_projects_owner_can_cancel(self, enqueue):
		self.request()
		frappe.set_user(PARTNER_ADMIN)
		with self.assertRaises(frappe.PermissionError):
			cancel_hire_request(self.project.name)

	def test_a_requested_quote_cant_be_shortlisted_or_dropped(self, enqueue):
		self.request()
		with self.assertRaises(frappe.ValidationError):
			set_quote_status(self.quote.name, "Not Interested")

	def test_an_unanswered_request_expires_after_a_week(self, enqueue):
		self.request()
		frappe.set_user("Administrator")
		frappe.db.set_value(
			"Customer Project",
			self.project.name,
			"hire_requested_on",
			add_days(now_datetime(), -HIRE_REQUEST_EXPIRY_DAYS - 1),
		)
		expire_hire_requests()
		self.assertEqual(self.states(), ("Shared", "Interested"))

	def test_a_recent_request_doesnt_expire(self, enqueue):
		self.request()
		frappe.set_user("Administrator")
		expire_hire_requests()
		self.assertEqual(self.states(), ("Hiring", "Hire Requested"))

	def test_withdrawing_keeps_when_the_brief_was_first_shared(self, enqueue):
		shared_on = frappe.db.get_value("Customer Project", self.project.name, "shared_on")
		self.request()
		cancel_hire_request(self.project.name)
		self.assertEqual(frappe.db.get_value("Customer Project", self.project.name, "shared_on"), shared_on)
