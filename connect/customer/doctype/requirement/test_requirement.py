# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer
from connect.customer.doctype.requirement.requirement import (
	get_my_requirement,
	get_requirement_snapshot,
	save_customer_requirement,
)
from connect.patches.use_one_set_of_company_sizes import OLD_TO_NEW
from connect.patches.use_one_set_of_company_sizes import execute as use_one_set_of_company_sizes
from connect.patches.use_project_budget_ranges_for_requirements import OLD_TO_NEW as OLD_TO_NEW_BUDGETS
from connect.patches.use_project_budget_ranges_for_requirements import execute as use_project_budget_ranges

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
				"industry": "Manufacturing",
				"looking_for": "Replace Existing ERP",
				"timeline": "Within 3 months",
				"budget": "$6k to $18k",
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
		self.assertEqual(saved.budget, "$6k to $18k")

	def test_rejects_an_industry_outside_the_list(self):
		with self.assertRaises(frappe.LinkValidationError):
			self.save_company(industry="Retail & Distribution")

	def test_stores_the_number_of_employees_as_company_size(self):
		self.save_company(company_size="11-50")

		self.assertEqual(frappe.db.get_value("Requirement", {"customer": COMPANY}, "company_size"), "11-50")
		self.assertEqual(get_my_requirement()["company_size"], "11-50")

	def test_refuses_a_size_outside_the_shared_ranges(self):
		with self.assertRaises(frappe.ValidationError):
			self.save_company(company_size="201-1000")

	def test_the_patch_moves_old_sizes_to_the_shared_ranges(self):
		requirement = frappe.db.get_value("Requirement", {"customer": COMPANY}, "name")
		for old, new in OLD_TO_NEW.items():
			frappe.db.set_value("Requirement", requirement, "company_size", old)
			use_one_set_of_company_sizes()
			self.assertEqual(frappe.db.get_value("Requirement", requirement, "company_size"), new)

	def test_the_patch_moves_old_budgets_to_the_project_ranges(self):
		requirement = frappe.db.get_value("Requirement", {"customer": COMPANY}, "name")
		for old, new in OLD_TO_NEW_BUDGETS.items():
			frappe.db.set_value("Requirement", requirement, "budget", old)
			use_project_budget_ranges()
			self.assertEqual(frappe.db.get_value("Requirement", requirement, "budget"), new)

	def test_refuses_an_industry_not_on_the_list(self):
		with self.assertRaises(frappe.ValidationError):
			self.save_company(industry="Spaceflight")

	def test_company_name_and_country_come_from_the_customer(self):
		frappe.db.set_value("Customer", COMPANY, "country", "Kenya")

		self.assertEqual(get_my_requirement()["country"], "Kenya")
		self.assertEqual(get_requirement_snapshot(COMPANY)["country"], "Kenya")
		self.assertEqual(get_requirement_snapshot(COMPANY)["company_name"], COMPANY)

	def test_a_country_from_settings_is_saved_on_the_customer(self):
		self.save_company(country="Kenya")

		self.assertEqual(frappe.db.get_value("Customer", COMPANY, "country"), "Kenya")
