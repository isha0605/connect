# Copyright (c) 2026
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer
from connect.patches import move_project_answers_to_one_place

BUYER = "move.answers.buyer@example.test"
COMPANY = "_Test Move Answers Co"


class TestMoveAnswersPatch(IntegrationTestCase):
	"""Old projects keep regions and work mode inside criteria, and apps and size on Requirement."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		make_buyer(BUYER, COMPANY)
		frappe.db.set_value("Customer", COMPANY, "company_size", "")
		self.project = frappe.get_doc({"doctype": "Customer Project", "project_name": "Old project"}).insert(
			ignore_permissions=True
		)
		self.project.db_set(
			{
				"user": BUYER,
				"regions": None,
				"criteria": frappe.as_json({"countries": ["India"], "work": ["remote"], "tiers": ["Gold"]}),
			}
		)
		requirement = frappe.get_doc(
			{
				"doctype": "Requirement",
				"customer": COMPANY,
				"industry": "Retail",
				"company_size": "51-200",
				"apps": [{"app": "ERPNext"}],
			}
		)
		requirement.insert(ignore_permissions=True)

	def test_answers_move_to_their_own_fields(self):
		move_project_answers_to_one_place.execute()

		project = frappe.get_doc("Customer Project", self.project.name)
		self.assertEqual(frappe.parse_json(project.regions), ["India"])
		self.assertEqual(frappe.parse_json(project.work_modes), ["remote"])
		self.assertEqual(frappe.parse_json(project.criteria), {"cities": [], "tiers": ["Gold"]})
		self.assertEqual([row.app for row in project.apps], ["ERPNext"])
		self.assertEqual(frappe.db.get_value("Customer", COMPANY, "company_size"), "51-200")
