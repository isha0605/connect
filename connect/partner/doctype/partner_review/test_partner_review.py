# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner
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

	def test_a_customer_who_hired_the_partner_on_connect_can(self):
		frappe.get_doc(
			{"doctype": "Partner Customer", "partner": PARTNER, "customer": "_Test Review Buyer Co", "source": "Connect"}
		).insert(ignore_permissions=True)

		frappe.set_user(self.buyer)
		self.assertTrue(get_my_review_for_partner(PARTNER)["can_review"])
		review = submit_partner_review(PARTNER, 5)

		self.assertEqual(frappe.db.get_value("Partner Review", review["name"], "verification"), "Hired on Connect")

	def test_only_the_author_edits_their_companys_review(self):
		frappe.get_doc(
			{"doctype": "Partner Customer", "partner": PARTNER, "customer": "_Test Review Buyer Co", "source": "Connect"}
		).insert(ignore_permissions=True)
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
		frappe.get_doc(
			{"doctype": "Partner Customer", "partner": PARTNER, "customer": "_Test Review Buyer Co", "source": "Connect"}
		).insert(ignore_permissions=True)
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
