# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer
from connect.customer.doctype.requirement.requirement import get_my_requirement, save_customer_requirement

BUYER = "requirement.buyer@example.test"
COMPANY = "_Test Requirement Co"


class IntegrationTestCompanyDetails(IntegrationTestCase):
	"""Settings' Company details save only the company's own fields on the customer's Requirement."""

	def setUp(self):
		make_buyer(BUYER, COMPANY)
		frappe.get_doc(
			{
				"doctype": "Requirement",
				"customer": COMPANY,
				"company_name": COMPANY,
				"country": "India",
				"industry": "Manufacturing",
				"looking_for": "Replace Existing ERP",
				"timeline": "Within 3 months",
				"budget": "₹2L–₹10L",  # noqa: RUF001
			}
		).insert(ignore_permissions=True)
		frappe.set_user(BUYER)
		self.addCleanup(frappe.set_user, "Administrator")

	def save_company(self, **values):
		details = {
			"country": "India",
			"industry": "Textile Manufacturing",
			"company_size": "11-50",
			"current_situation": "Zoho",
			"additional_notes": "Two warehouses",
		}
		return save_customer_requirement(**{**details, **values})

	def test_keeps_the_fields_it_does_not_ask(self):
		self.save_company()

		saved = frappe.get_last_doc("Requirement", filters={"customer": COMPANY})
		self.assertEqual(saved.industry, "Textile Manufacturing")
		self.assertEqual(saved.current_situation, "Zoho")
		self.assertEqual(saved.additional_notes, "Two warehouses")
		self.assertEqual(saved.looking_for, "Replace Existing ERP")
		self.assertEqual(saved.timeline, "Within 3 months")
		self.assertEqual(saved.budget, "₹2L–₹10L")  # noqa: RUF001

	def test_stores_the_number_of_employees_as_company_size(self):
		self.save_company(company_size="11-50")

		self.assertEqual(frappe.db.get_value("Requirement", {"customer": COMPANY}, "company_size"), "11–50")  # noqa: RUF001
		self.assertEqual(get_my_requirement()["employees"], "11-50")

	def test_refuses_an_industry_not_on_the_list(self):
		with self.assertRaises(frappe.ValidationError):
			self.save_company(industry="Spaceflight")
