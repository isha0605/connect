# Copyright (c) 2026
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.customer_project import share_requirements, update_requirements
from connect.customer.doctype.customer_project.test_hiring import PROJECT_ANSWERS, make_buyer
from connect.customer.doctype.customer_project.test_questions import (
	BUYER,
	COMPANY,
	MATCHING,
	make_matching_partner,
)

PARTNER_ADMIN = "questions.partner.admin@example.test"


class TestRequirementsUpdate(IntegrationTestCase):
	"""Edit on sent requirements: the partners who have them get the new version, and a quote
	made against the old one waits for the partner to confirm or redo it."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		make_buyer(BUYER, COMPANY)
		make_matching_partner()
		self.project = self.as_buyer(share_requirements, PROJECT_ANSWERS)["name"]
		self.quote = frappe.get_doc("Project Quote", {"customer_project": self.project, "partner": MATCHING})

	def as_buyer(self, method, *args):
		frappe.set_user(BUYER)
		try:
			return method(*args)
		finally:
			frappe.set_user("Administrator")

	def update(self, **answers):
		return self.as_buyer(update_requirements, self.project, answers)

	def quoted(self, status="Quoted"):
		self.quote.db_set({"status": status, "amount": 500000, "timeline_weeks": 10})

	def test_the_new_version_goes_to_each_partner_with_what_changed(self):
		self.update(budget="Over ₹40 lakh", problems=["slow_close"])

		quote = frappe.get_doc("Project Quote", self.quote.name)
		card = frappe.parse_json(frappe.db.get_value("Connect Message", quote.brief_message, "content"))
		self.assertNotEqual(quote.brief_message, self.quote.brief_message)
		self.assertEqual(
			(card["update"], card["changes"], card["budget"]), (True, ["budget", "to fix"], "Over ₹40 lakh")
		)
		line = frappe.get_all(
			"Connect Message", filters={"thread": quote.thread, "message_type": "System"}, pluck="content"
		)
		self.assertIn("Requirements updated · Changed: budget, to fix", line)
		self.assertTrue(frappe.db.get_value("Customer Project", self.project, "requirements_updated_on"))

	def test_nothing_changed_sends_nothing(self):
		before = frappe.db.count("Connect Message", {"thread": self.quote.thread})
		self.update(budget=PROJECT_ANSWERS["budget"])
		self.assertEqual(frappe.db.count("Connect Message", {"thread": self.quote.thread}), before)

	def test_a_quote_made_before_waits_for_the_partner(self):
		self.quoted()
		self.update(description="We also need payroll.")
		self.assertTrue(frappe.db.get_value("Project Quote", self.quote.name, "quoted_before_update"))

	def test_a_partner_set_aside_gets_nothing(self):
		self.quoted("Not Interested")
		brief = self.quote.brief_message
		self.update(description="We also need payroll.")
		self.assertEqual(frappe.db.get_value("Project Quote", self.quote.name, "brief_message"), brief)

	def test_quote_still_stands_clears_the_flag(self):
		self.quoted()
		self.update(description="We also need payroll.")

		frappe.set_user(PARTNER_ADMIN)
		frappe.get_doc("Project Quote", self.quote.name).confirm_quote()
		frappe.set_user("Administrator")

		self.assertFalse(frappe.db.get_value("Project Quote", self.quote.name, "quoted_before_update"))

	def test_a_redone_quote_keeps_the_customers_interest(self):
		self.quoted("Interested")
		self.update(description="We also need payroll.")

		frappe.set_user(PARTNER_ADMIN)
		frappe.get_doc("Project Quote", self.quote.name).send_quote(650000, 12, "With payroll")
		frappe.set_user("Administrator")

		quote = frappe.get_doc("Project Quote", self.quote.name)
		self.assertEqual((quote.status, quote.amount, quote.quoted_before_update), ("Interested", 650000, 0))

	def test_someone_else_cannot_confirm_a_quote(self):
		self.quoted()
		self.update(description="We also need payroll.")
		frappe.set_user(BUYER)
		self.assertRaises(
			frappe.PermissionError, frappe.get_doc("Project Quote", self.quote.name).confirm_quote
		)

	def test_requirements_are_locked_once_a_hire_is_asked(self):
		frappe.db.set_value("Customer Project", self.project, "status", "Hiring")
		with self.assertRaisesRegex(frappe.ValidationError, "choosing a partner"):
			self.update(description="Too late")

	def test_the_reply_says_how_many_got_it(self):
		from connect.customer.doctype.customer_project.brief import get_update_recipients

		recipients = len(get_update_recipients(self.project))
		self.assertEqual(self.update(description="We also need payroll.")["update_sent_to"], recipients)
		self.assertEqual(self.update(description="We also need payroll.")["update_sent_to"], 0)

	def test_only_the_owner_edits_from_the_current_card(self):
		from connect.customer.doctype.customer_project.brief import editable_briefs

		self.update(description="We also need payroll.")
		current = frappe.db.get_value("Project Quote", self.quote.name, "brief_message")
		self.assertEqual(
			self.as_buyer(editable_briefs, self.quote.thread), [{"brief_message": current, "project": self.project}]
		)
		frappe.set_user(PARTNER_ADMIN)
		self.assertEqual(editable_briefs(self.quote.thread), [])

	def test_no_card_edits_once_a_hire_is_asked(self):
		from connect.customer.doctype.customer_project.brief import editable_briefs

		frappe.db.set_value("Customer Project", self.project, "status", "Hiring")
		self.assertEqual(self.as_buyer(editable_briefs, self.quote.thread), [])

	def test_setting_a_quote_aside_clears_its_flag(self):
		self.quoted()
		self.update(description="We also need payroll.")
		quote = frappe.get_doc("Project Quote", self.quote.name)
		quote.status = "Not Interested"
		quote.save(ignore_permissions=True)
		self.assertFalse(frappe.db.get_value("Project Quote", self.quote.name, "quoted_before_update"))

	def test_a_flagged_quote_waits_while_the_customer_hires(self):
		self.quoted("Interested")
		self.update(description="We also need payroll.")
		frappe.db.set_value("Customer Project", self.project, "status", "Hiring")

		frappe.set_user(PARTNER_ADMIN)
		quote = frappe.get_doc("Project Quote", self.quote.name)
		self.assertFalse(quote.is_quotable())
		with self.assertRaisesRegex(frappe.ValidationError, "moved on"):
			quote.confirm_quote()
