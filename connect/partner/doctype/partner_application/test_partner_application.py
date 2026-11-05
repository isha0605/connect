# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.partner.doctype.partner_application.partner_application import get_mrr_status, unregister
from connect.partner.doctype.partner_certificate.partner_certificate import recount_certificates

PARTNER = "_Test Application Partner"
OWNER = "application.owner@example.test"
ACTIVE = "_Test Active Unapproved Partner"
IDLE = "_Test Idle Unapproved Partner"
ACTIVE_ADMIN = "patch.active.admin@example.test"
IDLE_ADMIN = "patch.idle.admin@example.test"
PATCH_BUYER = "patch.buyer@example.test"
UNREGISTER_PARTNER = "_Test Unregister Partner"
ADMIN = "unregister.admin@example.test"
MEMBER = "unregister.member@example.test"


class TestPartnerApplicationMRR(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		make_partner(PARTNER)
		make_partner_admin(PARTNER, OWNER)

	def apply(self, country, monthly_revenue):
		values = {"registered_country": country, "registered_state": "Gujarat" if country == "India" else None}
		return frappe.get_doc(
			{
				"doctype": "Partner Application",
				"partner": PARTNER,
				"company_name": PARTNER,
				"monthly_revenue": monthly_revenue,
				**values,
			}
		).insert(ignore_permissions=True)

	def mrr_status(self):
		frappe.set_user(OWNER)
		return get_mrr_status()

	def test_an_indian_partner_needs_ten_thousand_rupees(self):
		self.apply("India", 4000)
		status = self.mrr_status()
		self.assertEqual((status["currency"], status["target_amount"]), ("INR", 10000))
		self.assertEqual(status["progress"], 40)
		self.assertFalse(status["requirement_complete"])

	def test_a_partner_elsewhere_needs_a_hundred_dollars(self):
		self.apply("Germany", 120)
		status = self.mrr_status()
		self.assertEqual((status["currency"], status["target_amount"]), ("USD", 100))
		self.assertTrue(status["requirement_complete"])

	def test_an_application_below_the_target_cannot_be_submitted(self):
		doc = self.apply("India", 9999)
		with self.assertRaisesRegex(frappe.ValidationError, "minimum monthly revenue"):
			doc._validate_mrr()

		doc.monthly_revenue = 10000
		doc._validate_mrr()

	# ---- Before approval the sidebar has only Overview; after, the partner pages ----

	def test_the_partner_is_approved_once_verified(self):
		from connect.account import get_my_context

		for status, is_approved in (("Pending Review", False), ("Verified", True)):
			frappe.set_user("Administrator")
			frappe.db.set_value("Partner", PARTNER, "verification_status", status)
			frappe.set_user(OWNER)
			self.assertEqual(get_my_context()["partner"]["is_approved"], is_approved)


class TestApproveActivePartners(IntegrationTestCase):
	"""The patch that approves partners already working with customers before approval mattered."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		make_buyer(PATCH_BUYER, "Patch Buyer Co")
		for partner, admin in ((ACTIVE, ACTIVE_ADMIN), (IDLE, IDLE_ADMIN)):
			make_partner(partner)
			make_partner_admin(partner, admin)
			frappe.db.set_value("Partner", partner, "verification_status", "Pending Review")
			thread = frappe.get_doc({"doctype": "Connect Thread", "customer": "Patch Buyer Co", "partner": partner})
			thread.insert(ignore_permissions=True)
			self.message(thread.name, PATCH_BUYER)
			if partner == ACTIVE:
				self.message(thread.name, admin)

	def message(self, thread, sender):
		frappe.get_doc(
			{"doctype": "Connect Message", "thread": thread, "sender": sender, "content": "Hello"}
		).insert(ignore_permissions=True)

	def application(self, partner, submitted):
		doc = frappe.get_doc({"doctype": "Partner Application", "partner": partner, "company_name": partner})
		doc.insert(ignore_permissions=True)
		if submitted:
			doc.db_set({"docstatus": 1, "status": "Pending Review"})
		return doc.name

	def run_patch(self):
		from connect.patches.approve_active_partners import execute

		execute()

	def test_a_partner_who_answered_a_customer_is_approved(self):
		application = self.application(ACTIVE, submitted=True)
		self.run_patch()

		self.assertEqual(frappe.db.get_value("Partner", ACTIVE, "verification_status"), "Verified")
		self.assertEqual(frappe.db.get_value("Partner Application", application, ["status", "docstatus"]), ("Approved", 1))

	def test_a_customer_writing_to_a_partner_is_not_work(self):
		self.run_patch()
		self.assertEqual(frappe.db.get_value("Partner", IDLE, "verification_status"), "Pending Review")

	def test_a_draft_application_stays_a_draft(self):
		application = self.application(ACTIVE, submitted=False)
		self.run_patch()
		self.assertEqual(frappe.db.get_value("Partner Application", application, ["status", "docstatus"]), ("Draft", 0))


class IntegrationTestPartnerApplication(IntegrationTestCase):
	"""Opting out: the partner's admin may while onboarding, never once the partnership is approved."""

	def setUp(self):
		make_partner(UNREGISTER_PARTNER)
		make_partner_admin(UNREGISTER_PARTNER, ADMIN)
		if not frappe.db.exists("User", MEMBER):
			frappe.get_doc({"doctype": "User", "email": MEMBER, "first_name": "Member"}).insert(ignore_permissions=True)
		if not frappe.db.exists("Connect Partner Member", {"partner": UNREGISTER_PARTNER, "user": MEMBER}):
			frappe.get_doc({"doctype": "Connect Partner Member", "partner": UNREGISTER_PARTNER, "user": MEMBER}).insert(
				ignore_permissions=True
			)

		frappe.db.delete("Partner Application", {"partner": UNREGISTER_PARTNER})
		frappe.db.delete("Partner Certificate", {"partner_member_email": "holder.unregister@example.test"})
		self.application = frappe.get_doc(
			{"doctype": "Partner Application", "partner": UNREGISTER_PARTNER, "company_name": UNREGISTER_PARTNER}
		).insert(ignore_permissions=True)
		self.certificate = frappe.get_doc({
			"doctype": "Partner Certificate", "course": "erpnext-training", "partner": UNREGISTER_PARTNER,
			"partner_member_email": "holder.unregister@example.test",
		}).insert(ignore_permissions=True)
		recount_certificates(UNREGISTER_PARTNER)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_admin_opts_out_while_onboarding(self):
		frappe.set_user(MEMBER)
		with self.assertRaises(frappe.PermissionError):
			unregister()

		frappe.set_user(ADMIN)
		unregister()
		self.assertFalse(frappe.db.exists("Partner Application", self.application.name))
		self.assertIsNone(frappe.db.get_value("Partner Certificate", self.certificate.name, "partner"))
		self.assertEqual(frappe.db.get_value("Partner", UNREGISTER_PARTNER, "certs_erpnext"), 0)

	def test_approved_partnership_cannot_be_undone(self):
		self.application.db_set({"docstatus": 1, "status": "Approved"})
		frappe.set_user(ADMIN)
		with self.assertRaises(frappe.ValidationError):
			unregister()
		self.assertEqual(frappe.db.get_value("Partner Certificate", self.certificate.name, "partner"), UNREGISTER_PARTNER)
		self.assertEqual(frappe.db.get_value("Partner Application", self.application.name, "status"), "Approved")
