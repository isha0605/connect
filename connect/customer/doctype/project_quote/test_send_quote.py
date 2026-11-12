# Copyright (c) 2026, Isha and contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.api.projects import quotable_briefs, send_quote
from connect.customer.doctype.customer_project.brief import send_brief
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.customer.doctype.project_quote.test_leads import make_member

PARTNER = "_Test Quote Partner"
OTHER_PARTNER = "_Test Quote Other Partner"
OWNER = "quote.owner@example.test"
SALES = "quote.sales@example.test"
FINANCE = "quote.finance@example.test"
OTHER_OWNER = "quote.other.owner@example.test"
BUYER = "quote.buyer@example.test"


class IntegrationTestSendQuote(IntegrationTestCase):
	"""A partner's owners and sales quote on a brief from the chat, until the customer answers."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		# Notification emails and CRM syncs are queued; these tests check the quote, not them.
		patch("frappe.enqueue").start()
		self.addCleanup(patch.stopall)
		for partner, owner in ((PARTNER, OWNER), (OTHER_PARTNER, OTHER_OWNER)):
			make_partner(partner)
			make_partner_admin(partner, owner)
		make_member(PARTNER, SALES)
		make_member(PARTNER, FINANCE, "Finance")
		make_buyer(BUYER, "Quote Buyer Co")
		customer = frappe.db.get_value("Customer Team Member", {"user": BUYER}, "customer")
		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "Batch tracking", "status": "Shared", "user": BUYER}
		).insert(ignore_permissions=True)
		self.thread = send_brief(project, customer, PARTNER)
		self.quote = frappe.db.get_value("Project Quote", {"customer_project": project.name}, "name")

	def quote_as(self, user, amount=400000, weeks=6, note="Includes data migration."):
		frappe.set_user(user)
		try:
			return send_quote(self.quote, amount, weeks, note)["message"]
		finally:
			frappe.set_user("Administrator")

	def test_sales_quotes_from_the_chat(self):
		frappe.set_user(SALES)
		self.assertEqual([brief.project_name for brief in quotable_briefs(self.thread)], ["Batch tracking"])
		frappe.set_user("Administrator")

		message = self.quote_as(SALES)

		card = frappe.get_doc("Connect Message", message)
		self.assertEqual((card.message_type, card.sender, card.thread), ("Quote", SALES, self.thread))
		self.assertEqual(frappe.parse_json(card.content)["amount"], 400000)
		quote = frappe.get_doc("Project Quote", self.quote)
		self.assertEqual((quote.status, quote.amount, quote.timeline_weeks), ("Quoted", 400000, 6))
		self.assertEqual(quote.quote_message, message)
		# whoever quotes is in the thread, to answer the customer's questions
		self.assertTrue(frappe.db.exists("Connect Thread Member", {"thread": self.thread, "user": SALES, "is_removed": 0}))

	def test_a_quote_changes_until_the_customer_answers(self):
		first = self.quote_as(OWNER)
		second = self.quote_as(OWNER, amount=350000, weeks=8, note="")
		self.assertNotEqual(first, second)
		self.assertEqual(frappe.db.get_value("Project Quote", self.quote, ["status", "amount"]), ("Quoted", 350000))

		frappe.db.set_value("Project Quote", self.quote, "status", "Interested")
		self.assertRaises(frappe.ValidationError, self.quote_as, OWNER)
		frappe.set_user(OWNER)
		self.assertEqual(quotable_briefs(self.thread), [])

	def test_only_the_partners_owners_and_sales_quote(self):
		for user in (FINANCE, OTHER_OWNER, BUYER):
			self.assertRaises(frappe.PermissionError, self.quote_as, user)
			frappe.set_user(user)
			self.assertEqual(quotable_briefs(self.thread), [])
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Project Quote", self.quote, "status"), "Awaiting")

	def test_a_quote_needs_an_amount_and_a_sensible_timeline(self):
		for values in ({"amount": 0}, {"weeks": 0}, {"weeks": 105}, {"note": "x" * 301}):
			self.assertRaises(frappe.ValidationError, self.quote_as, OWNER, **values)
		self.assertEqual(frappe.db.get_value("Project Quote", self.quote, "status"), "Awaiting")
