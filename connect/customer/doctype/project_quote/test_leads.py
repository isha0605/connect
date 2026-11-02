# Copyright (c) 2026
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.brief import send_brief
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.customer.doctype.project_quote.leads import get_lead, my_leads, update_lead

PARTNER = "_Test Leads Partner"
OTHER_PARTNER = "_Test Leads Other Partner"
OWNER = "leads.owner@example.test"
SALES = "leads.sales@example.test"
OTHER_OWNER = "leads.other.owner@example.test"
BUYER = "leads.buyer@example.test"


def make_member(partner, email):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Sales"}).insert(ignore_permissions=True)
	if not frappe.db.exists("Connect Partner Member", {"partner": partner, "user": email}):
		frappe.get_doc({"doctype": "Connect Partner Member", "partner": partner, "user": email}).insert(
			ignore_permissions=True
		)


class TestLeads(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		# Each test changes the shared thread (revealing it, say); start every test afresh.
		self.addCleanup(frappe.db.rollback)
		# The new-requirement email job runs at once in tests and commits; these tests check data, not mail.
		patch("connect.notifications.frappe.enqueue").start()
		self.addCleanup(patch.stopall)
		for partner, owner in ((PARTNER, OWNER), (OTHER_PARTNER, OTHER_OWNER)):
			make_partner(partner)
			make_partner_admin(partner, owner)
		make_member(PARTNER, SALES)
		make_buyer(BUYER, "Leads Buyer Co")
		customer = frappe.db.get_value("Customer Team Member", {"user": BUYER}, "customer")

		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "Batch tracking", "status": "Shared", "user": BUYER}
		).insert(ignore_permissions=True)
		project.db_set("user", BUYER)
		self.thread = send_brief(project, customer, PARTNER)
		self.lead = frappe.db.get_value("Project Quote", {"customer_project": project.name}, "name")

	def as_user(self, user):
		frappe.set_user(user)

	def test_a_brief_is_an_open_lead_that_opens_on_its_brief(self):
		self.as_user(OWNER)
		self.assertIn(self.lead, [row["name"] for row in my_leads()["leads"]])

		lead = get_lead(self.lead)["lead"]
		self.assertEqual(lead["stage"], "Open")
		self.assertEqual(lead["company"], "Anonymous company")
		self.assertEqual(lead["messages"][0]["kind"], "brief")
		self.assertTrue(lead["needs_reply"])

	def test_a_member_off_the_thread_cannot_see_the_lead(self):
		self.as_user(SALES)
		self.assertNotIn(self.lead, [row["name"] for row in my_leads()["leads"]])
		self.assertRaises(frappe.DoesNotExistError, get_lead, self.lead)
		self.assertRaises(frappe.DoesNotExistError, update_lead, self.lead, probability="Hot")

	def test_another_partner_cannot_see_the_lead(self):
		self.as_user(OTHER_OWNER)
		self.assertRaises(frappe.DoesNotExistError, get_lead, self.lead)

	def test_a_customer_cannot_list_leads(self):
		self.as_user(BUYER)
		self.assertRaises(frappe.PermissionError, my_leads)

	def test_assigning_a_lead_adds_the_member_to_the_thread(self):
		self.as_user(OWNER)
		update_lead(self.lead, owner=SALES)

		self.as_user(SALES)
		self.assertEqual(get_lead(self.lead)["lead"]["owner"], SALES)
		self.assertTrue(
			frappe.db.exists("Connect Thread Member", {"thread": self.thread, "user": SALES, "is_removed": 0})
		)

	def test_a_lead_cannot_go_to_someone_off_the_team(self):
		self.as_user(OWNER)
		self.assertRaises(frappe.ValidationError, update_lead, self.lead, owner=OTHER_OWNER)

	def test_lost_needs_a_reason_and_won_comes_from_hiring(self):
		self.as_user(OWNER)
		self.assertRaises(frappe.ValidationError, update_lead, self.lead, stage="Lost")
		self.assertRaises(frappe.ValidationError, update_lead, self.lead, stage="Won")
		self.assertEqual(update_lead(self.lead, stage="Lost", lost_reason="No budget")["lost_reason"], "No budget")
		self.assertIsNone(update_lead(self.lead, stage="Negotiation")["lost_reason"])

	def test_hiring_the_partner_wins_the_lead(self):
		quote = frappe.get_doc("Project Quote", self.lead)
		quote.status = "Hired"
		quote.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Project Quote", self.lead, "lead_stage"), "Won")

		self.as_user(OWNER)
		self.assertRaises(frappe.ValidationError, update_lead, self.lead, stage="Open")
