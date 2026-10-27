# Copyright (c) 2026
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.partner_matching import (
	get_brief_recipients,
	normalize_criteria,
	partner_criteria,
)

CITY = "_Test Brief City"
WITH_ADMIN = "_Test Brief Partner With Admin"
WITHOUT_ADMIN = "_Test Brief Partner Without Admin"
ADMIN = "brief.partner.admin@example.test"
CRITERIA = {"cities": [CITY]}


def make_listed_partner(partner_name):
	if not frappe.db.exists("Partner", partner_name):
		tier = next(t for t in frappe.get_meta("Partner").get_field("tier").options.split("\n") if t)
		frappe.get_doc(
			{
				"doctype": "Partner",
				"partner_name": partner_name,
				"tier": tier,
				"country": "India",
				"city": CITY,
				"enabled": 1,
				"is_featured": 1,
			}
		).insert(ignore_permissions=True)


def make_admin(partner, email):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Admin"}).insert(ignore_permissions=True)
	if not frappe.db.exists("Connect Partner Member", {"partner": partner, "user": email}):
		frappe.get_doc(
			{"doctype": "Connect Partner Member", "partner": partner, "user": email, "is_admin": 1}
		).insert(ignore_permissions=True)


class TestBriefRecipients(IntegrationTestCase):
	def setUp(self):
		make_listed_partner(WITH_ADMIN)
		make_listed_partner(WITHOUT_ADMIN)
		make_admin(WITH_ADMIN, ADMIN)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_recipients_are_the_partners_the_brief_is_sent_to(self):
		recipients = partner_criteria(CRITERIA, include_recipients=True)["recipients"]

		self.assertEqual([r["name"] for r in recipients], get_brief_recipients(normalize_criteria(CRITERIA)))
		self.assertEqual([r["name"] for r in recipients], [WITH_ADMIN])

	def test_guest_gets_no_recipients(self):
		frappe.set_user("Guest")

		result = partner_criteria(CRITERIA, include_recipients=True)

		self.assertNotIn("recipients", result)
		self.assertEqual(result["total"], 2)
