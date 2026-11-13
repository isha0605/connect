# Copyright (c) 2026, Isha and contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.api.projects import decline_brief, list_quotes, quotable_briefs, send_quote
from connect.customer.doctype.customer_project.brief import send_brief
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.customer.doctype.project_quote.leads import get_lead
from connect.customer.doctype.project_quote.test_leads import make_member

PARTNER = "_Test Decline Partner"
OTHER_PARTNER = "_Test Decline Other Partner"
OWNER = "decline.owner@example.test"
SALES = "decline.sales@example.test"
FINANCE = "decline.finance@example.test"
OTHER_OWNER = "decline.other.owner@example.test"
BUYER = "decline.buyer@example.test"


class IntegrationTestDeclineBrief(IntegrationTestCase):
	"""A partner's owners and sales say "Not interested" to a brief before they quote on it."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		# Notification emails and CRM syncs are queued; these tests check the brief, not them.
		patch("frappe.enqueue").start()
		self.addCleanup(patch.stopall)
		for partner, owner in ((PARTNER, OWNER), (OTHER_PARTNER, OTHER_OWNER)):
			make_partner(partner)
			make_partner_admin(partner, owner)
		make_member(PARTNER, SALES)
		make_member(PARTNER, FINANCE, "Finance")
		make_buyer(BUYER, "Decline Buyer Co")
		self.customer = frappe.db.get_value("Customer Team Member", {"user": BUYER}, "customer")
		self.project = self.make_project("Batch tracking")
		self.thread = send_brief(self.project, self.customer, PARTNER)
		self.quote = frappe.db.get_value("Project Quote", {"customer_project": self.project.name}, "name")

	def make_project(self, name):
		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": name, "status": "Shared"}
		).insert(ignore_permissions=True)
		# before_insert stamps whoever is logged in, which is the Administrator here.
		project.db_set("user", BUYER)
		return project

	def decline_as(self, user, quote=None):
		frappe.set_user(user)
		try:
			decline_brief(quote or self.quote)
		finally:
			frappe.set_user("Administrator")

	def test_declining_tells_the_customer_and_loses_the_lead(self):
		self.decline_as(SALES)

		quote = frappe.get_doc("Project Quote", self.quote)
		self.assertEqual(quote.status, "Partner Declined")
		self.assertEqual(
			frappe.db.get_value("Partner Lead", quote.lead, ["stage", "lost_reason"]), ("Lost", "Not taking new clients")
		)
		notice = frappe.get_last_doc("Connect Message", {"thread": self.thread, "message_type": "System"})
		self.assertIn("not available to take on new clients", notice.content)

		frappe.set_user(BUYER)
		rows = list_quotes(self.project.name)
		self.assertEqual([(row.partner, row.status) for row in rows], [(PARTNER, "Partner Declined")])

	def test_a_declined_brief_cannot_be_quoted_or_declined_again(self):
		self.decline_as(OWNER)

		frappe.set_user(OWNER)
		self.assertEqual(quotable_briefs(self.thread), [])
		self.assertRaises(frappe.ValidationError, send_quote, self.quote, 400000, 6)
		self.assertRaises(frappe.ValidationError, decline_brief, self.quote)

	def test_a_quoted_brief_cannot_be_declined(self):
		frappe.set_user(OWNER)
		send_quote(self.quote, 400000, 6)

		self.assertRaises(frappe.ValidationError, decline_brief, self.quote)

	def test_only_the_partners_owners_and_sales_decline(self):
		for user in (FINANCE, OTHER_OWNER, BUYER):
			frappe.set_user(user)
			self.assertRaises(frappe.PermissionError, decline_brief, self.quote)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Project Quote", self.quote, "status"), "Awaiting")

	def test_another_open_brief_keeps_the_lead(self):
		second = self.make_project("Payroll")
		send_brief(second, self.customer, PARTNER)

		self.decline_as(OWNER)

		lead = frappe.db.get_value("Project Quote", self.quote, "lead")
		self.assertEqual(frappe.db.get_value("Partner Lead", lead, "stage"), "Open")

	def test_the_lead_shows_which_cards_can_be_answered(self):
		frappe.set_user(OWNER)
		lead = frappe.db.get_value("Project Quote", self.quote, "lead")
		card = next(m for m in get_lead(lead)["lead"]["messages"] if m["kind"] == "brief")
		self.assertEqual((card["quote"], card["can_answer"], card["is_declined"]), (self.quote, True, False))

		decline_brief(self.quote)

		card = next(m for m in get_lead(lead)["lead"]["messages"] if m["kind"] == "brief")
		self.assertEqual((card["can_answer"], card["is_declined"]), (False, True))
