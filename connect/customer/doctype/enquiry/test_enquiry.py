# Copyright (c) 2026, Isha and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.crm_enquiries import queue_enquiry_sync, sync_enquiry
from connect.customer.doctype.enquiry.enquiry import submit_enquiry
from connect.partner.doctype.partner_crm_settings.test_partner_crm_settings import FakeCRM

CRM = "connect.crm_enquiries"
SETTINGS = frappe._dict(name="_test_enquiry_crm", partner="_test_enquiry_crm", default_lead_status="New")
SOURCE_CACHE_KEY = "connect_crm_lead_source::_test_enquiry_crm::Connect Contact Form"

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = ["Customer", "User"]

FORM = {
	"first_name": " Asha ",
	"last_name": "Rao",
	"email": "Asha@Northwind.example",
	"phone": "+91 98765 43210",
	"company_name": "Northwind",
	"designation": "Director",
	"employees": "11-50",
	"current_software": "Tally",
	"industry": "Discrete Manufacturing",
	"state": "Maharashtra",
	"message": "Stock never matches the books.",
}


class IntegrationTestEnquiry(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_visitor_sends_an_enquiry(self):
		frappe.set_user("Guest")
		name = submit_enquiry(
			dict(FORM, status="Closed", user="Administrator"), source="Starter Pack Landing"
		)["name"]
		frappe.set_user("Administrator")

		doc = frappe.get_doc("Enquiry", name)
		self.assertEqual((doc.first_name, doc.email), ("Asha", "asha@northwind.example"))
		self.assertEqual((doc.status, doc.source), ("New", "Starter Pack Landing"))
		# fields the form doesn't have are never taken from it
		self.assertIsNone(doc.user)

	def test_a_wrong_email_or_a_missing_answer_is_refused(self):
		self.assertRaises(frappe.ValidationError, submit_enquiry, dict(FORM, email="asha@"))
		self.assertRaises(frappe.MandatoryError, submit_enquiry, dict(FORM, message=" "))
		self.assertRaises(frappe.ValidationError, submit_enquiry, dict(FORM, state="Atlantis"))

	def test_a_signed_in_visitor_is_linked(self):
		user = "_test_enquiry_buyer@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{"doctype": "User", "email": user, "first_name": "Buyer", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		customer = frappe.db.get_value("Customer", {"customer_name": "_Test Enquiry Co"}) or (
			frappe.get_doc({"doctype": "Customer", "customer_name": "_Test Enquiry Co"})
			.insert(ignore_permissions=True)
			.name
		)
		if not frappe.db.exists("Customer Team Member", {"user": user}):
			frappe.get_doc(
				{"doctype": "Customer Team Member", "customer": customer, "user": user, "is_admin": 1}
			).insert(ignore_permissions=True)

		frappe.set_user(user)
		name = submit_enquiry(FORM)["name"]
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Enquiry", name, ["user", "customer"]), (user, customer))


class IntegrationTestEnquiryInCRM(IntegrationTestCase):
	"""Each Contact us enquiry is a Lead on Frappe's CRM, for the sales team to pick up."""

	def setUp(self):
		frappe.cache.delete_value(SOURCE_CACHE_KEY)

	def enquiry(self, **values):
		with patch(f"{CRM}.frappe_crm", return_value=None):
			return submit_enquiry(dict(FORM, **values))["name"]

	def sync(self, enquiry, crm):
		with (
			patch(f"{CRM}.frappe_crm", return_value=SETTINGS),
			patch(f"{CRM}.crm_request", side_effect=crm),
			patch("connect.crm_integration.crm_request", side_effect=crm),
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback"),
			patch(f"{CRM}.frappe.log_error"),
		):
			sync_enquiry(enquiry)
		return frappe.db.get_value("Enquiry", enquiry, ["crm_lead_id", "crm_sync_status"], as_dict=True)

	def test_an_enquiry_is_sent_only_when_frappe_has_a_crm(self):
		doc = frappe.get_doc("Enquiry", self.enquiry())
		for settings, queued in ((None, False), (SETTINGS, True)):
			with patch(f"{CRM}.frappe_crm", return_value=settings), patch("frappe.enqueue") as enqueue:
				queue_enquiry_sync(doc)
			self.assertEqual(enqueue.called, queued)
		self.assertEqual(enqueue.call_args.kwargs["enquiry"], doc.name)

	def test_an_enquiry_becomes_a_lead_for_the_sales_team(self):
		enquiry = self.enquiry()
		crm = FakeCRM()

		self.assertEqual(
			self.sync(enquiry, crm), {"crm_lead_id": "CRM-LEAD-NEW", "crm_sync_status": "Synced"}
		)

		lead = crm.posted("/api/resource/CRM Lead")[0]
		self.assertEqual(
			lead,
			{
				"first_name": "Asha",
				"last_name": "Rao",
				"email": "asha@northwind.example",
				"mobile_no": "+91 98765 43210",
				"organization": "Northwind",
				"job_title": "Director",
				"no_of_employees": "11-50",
				"source": "Connect Contact Form",
				"status": "New",
			},
		)
		# Not on the CRM's list of industries, so it's in the email instead of on the Lead.
		email = crm.posted("/api/resource/Communication")[0]
		self.assertEqual((email["sent_or_received"], email["sender"]), ("Received", "asha@northwind.example"))
		self.assertEqual(email["reference_name"], "CRM-LEAD-NEW")
		self.assertTrue(email["content"].startswith("Stock never matches the books.<br><br>"))
		self.assertIn("Industry: Discrete Manufacturing", email["content"])

	def test_an_industry_and_size_the_crm_has_go_on_the_lead(self):
		enquiry = self.enquiry(industry="Manufacturing", employees="500+")
		crm = FakeCRM(industries=["Manufacturing"])
		self.sync(enquiry, crm)
		lead = crm.posted("/api/resource/CRM Lead")[0]
		self.assertEqual(lead["industry"], "Manufacturing")
		self.assertNotIn("no_of_employees", lead)  # the CRM has no "500+"
		self.assertIn("Company size: 500+", crm.posted("/api/resource/Communication")[0]["content"])

	def test_a_missing_source_is_added_to_the_crm_once(self):
		crm = FakeCRM(sources=[])
		self.sync(self.enquiry(), crm)
		self.sync(self.enquiry(), crm)
		self.assertEqual(
			crm.posted("/api/resource/CRM Lead Source"), [{"source_name": "Connect Contact Form"}]
		)

	def test_a_crm_that_wont_take_the_source_still_gets_the_lead(self):
		refuses = FakeCRM(sources=[], fail_on=lambda body: "source_name" in body)
		self.assertEqual(self.sync(self.enquiry(), refuses)["crm_sync_status"], "Synced")
		self.assertNotIn("source", refuses.posted("/api/resource/CRM Lead")[0])

	def test_a_failed_send_is_tried_again_without_a_second_lead(self):
		enquiry = self.enquiry()
		broken = FakeCRM(fail_on=lambda body: body.get("communication_type") == "Communication")
		self.assertEqual(
			self.sync(enquiry, broken), {"crm_lead_id": "CRM-LEAD-NEW", "crm_sync_status": "Failed"}
		)

		crm = FakeCRM()
		self.assertEqual(self.sync(enquiry, crm)["crm_sync_status"], "Synced")
		self.assertEqual(crm.posted("/api/resource/CRM Lead"), [])
		self.assertEqual(len(crm.posted("/api/resource/Communication")), 1)
