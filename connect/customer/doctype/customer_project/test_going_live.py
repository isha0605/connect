from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.brief import send_brief
from connect.customer.doctype.customer_project.customer_project import complete_project
from connect.customer.doctype.customer_project.going_live import not_live_yet
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.partner.doctype.partner_customer.customers import update_customer

PARTNER = "_Test Live Partner"
OWNER = "live.owner@example.test"
BUYER = "live.buyer@example.test"
COMPANY = "Live Buyer Co"
OTHER_BUYER = "live.other.buyer@example.test"


class TestGoingLive(IntegrationTestCase):
	"""The partner marks their customer Live; the customer confirms it, or says it isn't yet."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		patch("frappe.enqueue").start()
		self.addCleanup(patch.stopall)
		make_partner(PARTNER)
		make_partner_admin(PARTNER, OWNER)
		make_buyer(BUYER, COMPANY)
		make_buyer(OTHER_BUYER, "Live Other Buyer Co")

		self.project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "Warehouse barcodes", "status": "Shared"}
		).insert(ignore_permissions=True)
		self.project.db_set("user", BUYER)
		send_brief(self.project, COMPANY, PARTNER)
		quote = frappe.get_doc("Project Quote", {"customer_project": self.project.name})
		quote.status = "Hired"
		quote.save(ignore_permissions=True)
		self.thread = quote.thread
		self.customer = frappe.db.get_value("Partner Customer", {"partner": PARTNER, "customer": COMPANY}, "name")
		self.set_stage("Onboarding")

	def set_stage(self, stage):
		frappe.set_user(OWNER)
		try:
			update_customer(self.customer, stage=stage)
		finally:
			frappe.set_user("Administrator")

	def as_user(self, user, function, *args):
		frappe.set_user(user)
		try:
			return function(*args)
		finally:
			frappe.set_user("Administrator")

	def live_on(self):
		return frappe.db.get_value("Customer Project", self.project.name, "live_on")

	def test_the_partner_marking_their_customer_live_lets_the_customer_complete(self):
		self.assertRaises(frappe.ValidationError, self.as_user, BUYER, complete_project, self.project.name)

		self.set_stage("Live")

		self.assertTrue(self.live_on())
		self.as_user(BUYER, complete_project, self.project.name)
		self.assertEqual(frappe.db.get_value("Customer Project", self.project.name, "status"), "Completed")

	def test_not_live_yet_reopens_the_project_and_tells_the_partner(self):
		self.set_stage("Live")

		data = self.as_user(BUYER, not_live_yet, self.project.name)

		self.assertIsNone(data["live_on"])
		self.assertIsNone(self.live_on())
		self.assertEqual(frappe.db.get_value("Partner Customer", self.customer, "stage"), "Onboarding")
		note = frappe.get_all(
			"Connect Message", filters={"thread": self.thread, "message_type": "System"}, pluck="content"
		)
		self.assertIn(f"{COMPANY} says Warehouse barcodes isn't live yet.", note)

	def test_only_the_project_owner_can_say_it_isnt_live(self):
		self.set_stage("Live")

		self.assertRaises(frappe.PermissionError, self.as_user, OTHER_BUYER, not_live_yet, self.project.name)
		self.assertTrue(self.live_on())

	def test_moving_the_customer_off_live_takes_the_mark_back(self):
		self.set_stage("Live")
		self.set_stage("Onboarding")

		self.assertIsNone(self.live_on())
		self.assertRaises(frappe.ValidationError, self.as_user, BUYER, complete_project, self.project.name)

	def test_hiring_a_live_customer_again_starts_them_at_onboarding(self):
		self.set_stage("Live")
		self.as_user(BUYER, complete_project, self.project.name)

		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "Second site", "status": "Shared"}
		).insert(ignore_permissions=True)
		project.db_set("user", BUYER)
		send_brief(project, COMPANY, PARTNER)
		quote = frappe.get_doc("Project Quote", {"customer_project": project.name})
		quote.status = "Hired"
		quote.save(ignore_permissions=True)

		self.assertEqual(frappe.db.get_value("Partner Customer", self.customer, "stage"), "Onboarding")
		self.assertIsNone(frappe.db.get_value("Customer Project", project.name, "live_on"))

	def test_not_live_yet_needs_a_live_mark(self):
		self.assertRaises(frappe.ValidationError, self.as_user, BUYER, not_live_yet, self.project.name)
