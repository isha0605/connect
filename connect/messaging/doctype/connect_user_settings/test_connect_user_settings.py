# Copyright (c) 2026
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer
from connect.messaging.doctype.connect_user_settings.connect_user_settings import update_my_settings
from connect.partner.doctype.partner.test_partner import make_partner

PARTNER = "_Test Hours Partner"
PARTNER_OWNER = "hours.owner@example.test"
BUYER = "hours.buyer@example.test"
HOURS = ("09:00", "18:00", ["monday", "tuesday"], "Do nothing")


class IntegrationTestWorkingHours(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		make_partner(PARTNER, "Pending Review")
		if not frappe.db.exists("User", PARTNER_OWNER):
			frappe.get_doc({"doctype": "User", "email": PARTNER_OWNER, "first_name": "Owner"}).insert(
				ignore_permissions=True
			)
		if not frappe.db.exists("Connect Partner Member", {"user": PARTNER_OWNER}):
			frappe.get_doc(
				{"doctype": "Connect Partner Member", "partner": PARTNER, "user": PARTNER_OWNER, "access": "Owner"}
			).insert(ignore_permissions=True)

	def test_a_partner_frappe_has_not_approved_cannot_set_working_hours(self):
		frappe.set_user(PARTNER_OWNER)
		with self.assertRaisesRegex(frappe.PermissionError, "once Frappe approves"):
			update_my_settings(*HOURS)

	def test_an_approved_partner_sets_working_hours(self):
		frappe.db.set_value("Partner", PARTNER, "verification_status", "Verified")
		frappe.set_user(PARTNER_OWNER)
		self.assertEqual(update_my_settings(*HOURS)["work_start"], "09:00")

	def test_a_customer_sets_working_hours(self):
		make_buyer(BUYER, "_Test Hours Customer")
		frappe.set_user(BUYER)
		self.assertEqual(update_my_settings(*HOURS)["work_end"], "18:00")
