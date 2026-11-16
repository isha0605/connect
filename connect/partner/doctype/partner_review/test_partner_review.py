# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.customer_project import is_partner_reviewed
from connect.customer.doctype.customer_project.test_hiring import complete_a_project, make_buyer, make_partner
from connect.partner.doctype.review_request.test_review_request import make_reviewer
from connect.partner.doctype.partner_review.partner_review import get_my_review_for_partner, submit_partner_review

PARTNER = "_Test Review Partner"


class TestWhoReviews(IntegrationTestCase):
	"""Only a partner's real customers review it."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")
		make_partner(PARTNER)
		self.buyer = make_buyer("review.buyer@example.test", "_Test Review Buyer Co")

	def test_a_stranger_cannot_review(self):
		frappe.set_user(self.buyer)
		self.assertFalse(get_my_review_for_partner(PARTNER)["can_review"])
		with self.assertRaises(frappe.PermissionError):
			submit_partner_review(PARTNER, 5)

	def test_a_hire_alone_is_not_enough(self):
		frappe.get_doc(
			{"doctype": "Partner Customer", "partner": PARTNER, "customer": "_Test Review Buyer Co", "source": "Connect"}
		).insert(ignore_permissions=True)
		complete_a_project(self.buyer, PARTNER, status="Hired")

		frappe.set_user(self.buyer)
		self.assertFalse(get_my_review_for_partner(PARTNER)["can_review"])
		with self.assertRaises(frappe.PermissionError):
			submit_partner_review(PARTNER, 5)

	def test_a_customer_who_completed_a_project_with_the_partner_can(self):
		project = complete_a_project(self.buyer, PARTNER)
		self.assertFalse(is_partner_reviewed(project))

		frappe.set_user(self.buyer)
		self.assertTrue(get_my_review_for_partner(PARTNER)["can_review"])
		review = submit_partner_review(PARTNER, 5)
		frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Partner Review", review["name"], "verification"), "Hired on Connect")
		self.assertTrue(is_partner_reviewed(project))

	def test_only_the_author_edits_their_companys_review(self):
		complete_a_project(self.buyer, PARTNER)
		frappe.set_user(self.buyer)
		submit_partner_review(PARTNER, 5, headline="Great work")
		frappe.set_user("Administrator")
		teammate = make_buyer("review.teammate@example.test", "_Test Review Buyer Co")

		frappe.set_user(teammate)
		self.assertEqual(
			get_my_review_for_partner(PARTNER), {"review": None, "can_review": False, "reviewed_by_teammate": True}
		)
		with self.assertRaises(frappe.PermissionError):
			submit_partner_review(PARTNER, 1, headline="Not great")
		frappe.set_user("Administrator")

		self.assertEqual(
			frappe.db.get_value("Partner Review", {"partner": PARTNER}, ["rating", "headline"]), (5, "Great work")
		)

	def test_a_hidden_review_does_not_count(self):
		complete_a_project(self.buyer, PARTNER)
		frappe.set_user(self.buyer)
		review = submit_partner_review(PARTNER, 2)
		frappe.set_user("Administrator")

		reviewer = make_reviewer("review.moderator@example.test")
		frappe.set_user(self.buyer)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Partner Review", review["name"]).hide("Not a customer")

		frappe.set_user(reviewer)
		doc = frappe.get_doc("Partner Review", review["name"])
		with self.assertRaises(frappe.ValidationError):
			doc.hide("")
		doc.hide("Not a customer")
		frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "rating"), 0)
		self.assertEqual(
			frappe.db.get_value("Partner Review", review["name"], ["is_hidden", "hidden_reason"]), (1, "Not a customer")
		)
