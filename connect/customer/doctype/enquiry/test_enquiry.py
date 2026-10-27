# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.enquiry.enquiry import submit_enquiry

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

