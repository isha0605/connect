# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner
from connect.patches import link_industry_fields_to_industry as patch

BUYER = "industry.buyer@example.test"
COMPANY = "_Test Industry Co"
PARTNER = "_Test Industry Rename Partner"
OLD_INDUSTRY = "_Test Old Industry"


class IntegrationTestIndustryList(IntegrationTestCase):
	"""The patch moves every stored industry onto frappe.io's list before it deletes anything."""

	def setUp(self):
		patch.create_industries()
		make_buyer(BUYER, COMPANY)
		make_partner(PARTNER)
		make_industry(OLD_INDUSTRY)

	def test_renames_old_values_everywhere(self):
		# Written straight to the table: the Link field no longer accepts this value.
		requirement = self.make_requirement()
		frappe.db.set_value("Requirement", requirement, "industry", "Retail & Distribution")

		patch.execute()

		self.assertEqual(frappe.db.get_value("Requirement", requirement, "industry"), "Trading and Distribution")

	def test_a_partner_with_the_old_and_new_name_keeps_one(self):
		make_industry("Finance")
		doc = frappe.get_doc("Partner", PARTNER)
		doc.set("industries", [{"industry": "Finance"}, {"industry": "Banking, Insurance and Broking"}])
		doc.save(ignore_permissions=True)

		patch.execute()

		picked = frappe.get_all("Partner Industry", filters={"parent": PARTNER, "parentfield": "industries"}, pluck="industry")
		self.assertEqual(picked, ["Banking, Insurance and Broking"])

	def test_deletes_industries_outside_the_list(self):
		patch.execute()

		self.assertFalse(frappe.db.exists("Industry", OLD_INDUSTRY))
		self.assertEqual(frappe.db.get_value("Industry", "Livestock", "industry_group"), "Others")

	def test_stops_before_deleting_when_a_value_has_no_new_name(self):
		requirement = self.make_requirement()
		frappe.db.set_value("Requirement", requirement, "industry", OLD_INDUSTRY)

		with self.assertRaises(frappe.ValidationError):
			patch.execute()
		self.assertTrue(frappe.db.exists("Industry", OLD_INDUSTRY))

	def make_requirement(self) -> str:
		return frappe.get_doc(
			{
				"doctype": "Requirement",
				"customer": COMPANY,
				"company_name": COMPANY,
				"country": "India",
				"industry": "Manufacturing",
			}
		).insert(ignore_permissions=True).name


def make_industry(name: str) -> None:
	if not frappe.db.exists("Industry", name):
		frappe.get_doc({"doctype": "Industry", "title": name}).insert(ignore_permissions=True)
