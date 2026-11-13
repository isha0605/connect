# Copyright (c) 2026
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.brief import send_brief
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin

PARTNER = "_Test Hire Partner"
OTHER_PARTNER = "_Test Hire Other Partner"
ADMINS = {PARTNER: "hire.admin@example.test", OTHER_PARTNER: "hire.other.admin@example.test"}
BUYER = "hire.buyer@example.test"
COMPANY = "Hire Buyer Co"


class TestHireOwnership(IntegrationTestCase):
	"""Project Quote owns the hire: its project, lead and the partner's customer follow it."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		# The new-requirement email job runs at once in tests and commits; these tests check data.
		patch("connect.notifications.frappe.enqueue").start()
		self.addCleanup(patch.stopall)
		for partner, admin in ADMINS.items():
			make_partner(partner)
			make_partner_admin(partner, admin)
		make_buyer(BUYER, COMPANY)

		self.project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "Plant rollout", "status": "Shared", "user": BUYER}
		).insert(ignore_permissions=True)
		self.project.db_set("user", BUYER)
		send_brief(self.project, COMPANY, PARTNER)
		send_brief(self.project, COMPANY, OTHER_PARTNER)
		self.quote = self.quote_of(PARTNER)

	def quote_of(self, partner):
		return frappe.get_doc("Project Quote", {"customer_project": self.project.name, "partner": partner})

	def set_quote(self, status, quote=None):
		quote = quote or self.quote
		quote.status = status
		quote.save(ignore_permissions=True)

	def records(self):
		"""Where the hire stands on each record that shows it."""
		self.project.reload()
		lead = frappe.db.get_value("Partner Lead", self.quote.lead, "stage")
		customer = frappe.db.exists("Partner Customer", {"partner": PARTNER, "customer": COMPANY})
		return self.project.status, self.project.hired_quote, self.project.partner, lead, bool(customer)

	def test_a_hire_shows_on_the_project_the_lead_and_the_partners_customers(self):
		self.set_quote("Hire Requested")
		self.assertEqual(self.records(), ("Hiring", self.quote.name, PARTNER, "Open", False))

		self.set_quote("Hired")
		self.assertEqual(self.records(), ("Hired", self.quote.name, PARTNER, "Won", True))

	def test_a_request_that_ends_without_a_hire_frees_the_project(self):
		for ending in ("Hire Declined", "Quoted"):
			with self.subTest(ending=ending):
				self.set_quote("Hire Requested")
				self.set_quote(ending)
				self.assertEqual(self.records(), ("Shared", None, None, "Open", False))

	def test_only_one_partner_is_hired_or_asked_at_a_time(self):
		self.set_quote("Hire Requested")
		with self.assertRaises(frappe.ValidationError):
			self.set_quote("Hire Requested", self.quote_of(OTHER_PARTNER))

	def test_the_project_and_lead_are_not_hired_by_hand(self):
		self.project.status = "Hired"
		with self.assertRaises(frappe.ValidationError):
			self.project.save(ignore_permissions=True)

		lead = frappe.get_doc("Partner Lead", self.quote.lead)
		lead.stage = "Won"
		with self.assertRaises(frappe.ValidationError):
			lead.save(ignore_permissions=True)

	def test_a_won_lead_and_a_completed_hire_stay_as_they_are(self):
		self.set_quote("Hired")
		lead = frappe.get_doc("Partner Lead", self.quote.lead)
		lead.stage = "Lost"
		lead.lost_reason = "Other"
		with self.assertRaises(frappe.ValidationError):
			lead.save(ignore_permissions=True)

		self.project.reload()
		self.project.status = "Completed"
		self.project.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self.set_quote("Hire Declined")
