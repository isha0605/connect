# Copyright (c) 2026
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.customer_project import set_quote_status
from connect.customer.doctype.customer_project.project_notifications import send_quote_declined_email
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin

PARTNER = "_Test Decline Partner"
BUYER = "decline.buyer@example.test"
PARTNER_ADMIN = "decline.partner.admin@example.test"
EMAIL_JOB = "connect.customer.doctype.customer_project.project_notifications.send_quote_declined_email"


class TestQuoteDecline(IntegrationTestCase):
	"""The customer setting a quote aside: the partner's lead is lost and they're emailed why;
	Restore takes it back."""

	def setUp(self):
		from connect.starter_packs.doctype.starter_pack_order.implementation import get_or_open_thread

		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		make_partner(PARTNER)
		make_partner_admin(PARTNER, PARTNER_ADMIN)
		make_buyer(BUYER, "Decline Buyer Co")
		customer = frappe.db.get_value("Customer Team Member", {"user": BUYER}, "customer")
		self.thread = get_or_open_thread(customer, PARTNER, BUYER)
		self.quote = self.make_quote("ERP rollout")
		self.lead = frappe.db.get_value("Project Quote", self.quote, "lead")
		self.enqueue = patch("connect.customer.doctype.customer_project.project_notifications.frappe.enqueue").start()
		self.addCleanup(patch.stopall)

	def make_quote(self, project_name, status="Quoted"):
		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": project_name, "status": "Shared", "user": BUYER}
		).insert(ignore_permissions=True)
		project.db_set("user", BUYER)
		return frappe.get_doc(
			{
				"doctype": "Project Quote", "customer_project": project.name, "partner": PARTNER,
				"thread": self.thread, "status": status, "amount": 875000, "currency": "INR", "timeline_weeks": 8,
			}
		).insert(ignore_permissions=True).name

	def decide(self, status, reason=None, note=None, quote=None):
		frappe.set_user(BUYER)
		try:
			return set_quote_status(quote or self.quote, status, reason, note)
		finally:
			frappe.set_user("Administrator")

	def lead_state(self):
		return frappe.db.get_value("Partner Lead", self.lead, ["stage", "lost_reason"])

	def emailed(self):
		return [call.kwargs["user"] for call in self.enqueue.call_args_list if call.args[0] == EMAIL_JOB]

	def test_a_reason_is_required(self):
		with self.assertRaisesRegex(frappe.ValidationError, "why you're not interested"):
			self.decide("Not Interested")

	def test_not_interested_loses_the_lead_and_emails_the_partner(self):
		self.decide("Not Interested", "Price", "Too far over our budget")

		self.assertEqual(self.lead_state(), ("Lost", "Customer declined the quote"))
		quote = frappe.db.get_value("Project Quote", self.quote, ["not_interested_reason", "not_interested_note"])
		self.assertEqual(quote, ("Price", "Too far over our budget"))
		self.assertIn(PARTNER_ADMIN, self.emailed())

	def test_another_open_requirement_keeps_the_lead_but_still_emails(self):
		self.make_quote("HR rollout")
		self.decide("Not Interested", "Timeline")

		self.assertNotEqual(self.lead_state()[0], "Lost")
		self.assertIn(PARTNER_ADMIN, self.emailed())

	def test_restore_reopens_a_lead_lost_to_the_decline(self):
		self.decide("Not Interested", "Price")
		self.decide("Quoted")

		self.assertEqual(self.lead_state(), ("Open", None))
		quote = frappe.db.get_value("Project Quote", self.quote, ["not_interested_reason", "not_interested_note"])
		self.assertEqual(quote, (None, None))

	def test_restore_leaves_a_lead_the_partner_closed_themselves(self):
		self.decide("Not Interested", "Price")
		frappe.db.set_value("Partner Lead", self.lead, "lost_reason", "No budget")
		self.decide("Quoted")

		self.assertEqual(self.lead_state(), ("Lost", "No budget"))

	def test_the_email_names_the_quote_and_the_reason(self):
		self.decide("Not Interested", "Picked another partner", "Went with a local firm")

		with patch("connect.customer.doctype.customer_project.project_notifications.frappe.sendmail") as sendmail:
			send_quote_declined_email(PARTNER_ADMIN, self.quote)

		mail = sendmail.call_args.kwargs
		self.assertEqual(mail["subject"], "Decline Buyer Co declined your quote for ERP rollout")
		for part in ("₹8,75,000", "8 weeks", "Picked another partner", "Went with a local firm", self.lead):
			self.assertIn(part, mail["message"])

	def test_the_lost_lead_is_sent_to_the_partners_crm(self):
		with (
			patch("connect.crm_stage_sync.queue_stage_sync") as stage_sync,
			patch("connect.crm_partner_leads.queue_partner_lead_sync") as lead_sync,
		):
			self.decide("Not Interested", "Not a good fit")

		self.assertEqual(stage_sync.call_args.args[0].stage, "Lost")
		self.assertIn(self.lead, [call.args[0] for call in lead_sync.call_args_list])
