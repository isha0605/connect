# Copyright (c) 2026
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer
from connect.patches import move_project_answers_to_one_place

BUYER = "move.answers.buyer@example.test"
COMPANY = "_Test Move Answers Co"


class TestMoveAnswersPatch(IntegrationTestCase):
	"""Old projects keep the company's country and industries inside criteria, and apps and
	size on Requirement."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		make_buyer(BUYER, COMPANY)
		customer = frappe.get_doc("Customer", COMPANY)
		customer.country = ""
		customer.company_size = ""
		customer.set("industries", [])
		customer.save(ignore_permissions=True)
		self.project = frappe.get_doc({"doctype": "Customer Project", "project_name": "Old project"}).insert(
			ignore_permissions=True
		)
		self.project.db_set(
			{
				"user": BUYER,
				"criteria": frappe.as_json(
					{"countries": ["India"], "work": ["remote"], "industries": ["Retail"], "tiers": ["Gold"]}
				),
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
		self.assertEqual(frappe.parse_json(project.criteria), {"cities": [], "tiers": ["Gold"]})
		self.assertEqual([row.app for row in project.apps], ["ERPNext"])
		customer = frappe.get_doc("Customer", COMPANY)
		self.assertEqual((customer.country, customer.company_size), ("India", "51-200"))
		# No industries answered anywhere, so Edit criteria's pick describes the company.
		self.assertEqual(customer.get_industries(), ["Retail"])


class TestDeleteDraftProjects(IntegrationTestCase):
	"""A new project is shared as it is saved, so drafts are deleted; sent projects stay."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)

	def test_drafts_go_and_sent_projects_stay(self):
		from connect.patches import delete_draft_projects

		draft = frappe.get_doc({"doctype": "Customer Project", "project_name": "Old draft"}).insert(
			ignore_permissions=True
		)
		sent = frappe.get_doc({"doctype": "Customer Project", "project_name": "Sent"}).insert(
			ignore_permissions=True
		)
		sent.db_set("status", "Shared")

		delete_draft_projects.execute()

		self.assertFalse(frappe.db.exists("Customer Project", draft.name))
		self.assertTrue(frappe.db.exists("Customer Project", sent.name))
