# Copyright (c) 2026
# See license.txt

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime

from connect.customer.doctype.customer_project.test_hiring import make_partner, make_partner_admin
from connect.partner.doctype.connect_partner_member.test_switch_partner import add_member
from connect.partner.doctype.partner_review.partner_review import submit_partner_review
from connect.partner.doctype.review_request import review_request as requests

PARTNER = "_Test Review Partner"
OTHER_PARTNER = "_Test Review Other Partner"
OWNER = "owner@review-partner.test"
OTHER_OWNER = "owner@review-other.test"
FINANCE = "finance@review-partner.test"
REVIEWER = "reviewer.staff@example.test"


class TestReviewRequest(IntegrationTestCase):
	"""A partner asks a past customer for a review; the customer answers from the emailed link."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.sendmail = patch("frappe.sendmail").start()
		self.notify = patch("frappe.desk.doctype.notification_log.notification_log.enqueue_create_notification").start()
		self.login_manager = MagicMock()
		patch.object(frappe.local, "login_manager", self.login_manager, create=True).start()
		self.addCleanup(patch.stopall)
		self.addCleanup(frappe.set_user, "Administrator")

		for partner, owner in ((PARTNER, OWNER), (OTHER_PARTNER, OTHER_OWNER)):
			make_partner(partner)
			make_partner_admin(partner, owner)
		add_member(PARTNER, FINANCE, access="Finance")
		self.customer_email = f"ravi.{frappe.generate_hash(length=6)}@acme-steel.test"

	def ask(self, email=None, send=True, user=OWNER):
		frappe.set_user(user)
		request = requests.create_request(
			{
				"contact_name": "Ravi Kumar",
				"contact_email": email or self.customer_email,
				"company_name": f"Acme Steel {frappe.generate_hash(length=6)}",
				"project_title": "ERPNext rollout",
			},
			send=send,
		)
		frappe.set_user("Administrator")
		return request

	def link_token(self):
		link = self.sendmail.call_args.kwargs["args"]["link"]
		return parse_qs(urlparse(link).query)["review"][0]

	def test_sending_emails_a_one_time_link(self):
		request = self.ask()

		self.assertEqual(request["status"], "Sent")
		self.assertEqual(self.sendmail.call_args.kwargs["recipients"], [self.customer_email])
		self.assertEqual(requests.open_request(self.link_token())["partner_name"], PARTNER)
		self.assertEqual(frappe.db.get_value("Review Request", request["name"], "status"), "Opened")

	def test_only_owners_and_sales_ask_and_only_for_their_partner(self):
		with self.assertRaises(frappe.PermissionError):
			self.ask(user=FINANCE)

		request = self.ask()
		frappe.set_user(OTHER_OWNER)
		with self.assertRaises(frappe.DoesNotExistError):
			requests.withdraw_request(request["name"])
		self.assertEqual(requests.my_requests(), [])

	def test_a_partner_cannot_ask_its_own_people_or_ask_twice(self):
		for email in (OTHER_OWNER, "someone@review-partner.test"):
			with self.subTest(email=email), self.assertRaises(frappe.ValidationError):
				self.ask(email=email)

		self.ask()
		with self.assertRaises(frappe.ValidationError):
			self.ask()

	def test_a_free_email_is_flagged(self):
		request = self.ask(email=f"ravi.{frappe.generate_hash(length=6)}@gmail.com")

		self.assertTrue(frappe.db.get_value("Review Request", request["name"], "is_free_email"))

	def test_accepting_signs_in_a_new_customer_who_can_then_review(self):
		request = self.ask()

		requests.accept_request(self.link_token(), "Ravi Kumar", f"Acme Steel {frappe.generate_hash(length=6)}")

		self.login_manager.login_as.assert_called_once_with(self.customer_email)
		self.assertEqual(frappe.db.get_value("Review Request", request["name"], "status"), "Accepted")
		frappe.set_user(self.customer_email)
		review = submit_partner_review(PARTNER, 4, headline="Solid rollout")
		frappe.set_user("Administrator")

		self.assertEqual(
			frappe.db.get_value("Partner Review", review["name"], ["verification", "review_request"]),
			("Confirmed by customer", request["name"]),
		)
		self.assertEqual(
			frappe.db.get_value("Review Request", request["name"], ["status", "review"]), ("Reviewed", review["name"])
		)
		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "rating"), 4)

	def test_a_link_works_once_and_not_after_it_expires_or_is_withdrawn(self):
		self.ask()
		token = self.link_token()
		requests.accept_request(token, "Ravi Kumar", f"Acme Steel {frappe.generate_hash(length=6)}")
		with self.assertRaises(frappe.DoesNotExistError):
			requests.open_request(token)

		expired = self.ask(email=f"old.{frappe.generate_hash(length=6)}@acme-steel.test")
		frappe.db.set_value("Review Request", expired["name"], "expires_on", add_days(now_datetime(), -1))
		with self.assertRaises(frappe.DoesNotExistError):
			requests.open_request(self.link_token())

		withdrawn = self.ask(email=f"gone.{frappe.generate_hash(length=6)}@acme-steel.test")
		frappe.set_user(OWNER)
		requests.withdraw_request(withdrawn["name"])
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.DoesNotExistError):
			requests.open_request(self.link_token())

	def test_declining_tells_the_partner_and_frappes_reviewers(self):
		make_reviewer(REVIEWER)
		request = self.ask()

		requests.decline_request(self.link_token(), "Never heard of them")

		self.assertEqual(
			frappe.db.get_value("Review Request", request["name"], ["status", "decline_reason"]),
			("Declined", "Never heard of them"),
		)
		told = self.notify.call_args.args[0]
		self.assertIn(OWNER, told)
		self.assertIn(REVIEWER, told)

	def test_a_reminder_is_sent_once_and_not_too_soon(self):
		request = self.ask()
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.ValidationError):
			requests.remind_request(request["name"])

		frappe.db.set_value("Review Request", request["name"], "sent_on", add_days(now_datetime(), -4))
		requests.remind_request(request["name"])
		self.assertTrue(self.sendmail.call_args.kwargs["args"]["reminder"])
		with self.assertRaises(frappe.ValidationError):
			requests.remind_request(request["name"])


def make_reviewer(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Reviewer"}).insert(ignore_permissions=True)
	frappe.get_doc("User", email).add_roles("Partner Reviewer")
