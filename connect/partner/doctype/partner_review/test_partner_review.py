# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner
from connect.partner.doctype.partner_review.partner_review import submit_partner_review

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
		with self.assertRaises(frappe.PermissionError):
			submit_partner_review(PARTNER, 5)

	def test_a_customer_who_hired_the_partner_on_connect_can(self):
		frappe.get_doc(
			{"doctype": "Partner Customer", "partner": PARTNER, "customer": "_Test Review Buyer Co", "source": "Connect"}
		).insert(ignore_permissions=True)

		frappe.set_user(self.buyer)
		review = submit_partner_review(PARTNER, 5)

		self.assertEqual(frappe.db.get_value("Partner Review", review["name"], "verification"), "Hired on Connect")

	def test_a_hidden_review_does_not_count(self):
		frappe.get_doc(
			{"doctype": "Partner Customer", "partner": PARTNER, "customer": "_Test Review Buyer Co", "source": "Connect"}
		).insert(ignore_permissions=True)
		frappe.set_user(self.buyer)
		review = submit_partner_review(PARTNER, 2)
		frappe.set_user("Administrator")

		frappe.get_doc("Partner Review", review["name"]).update({"is_hidden": 1}).save()

		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "rating"), 0)
