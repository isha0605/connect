# Copyright (c) 2026
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.customer_project import (
	delete_project,
	save_criteria,
	save_project,
)
from connect.customer.doctype.customer_project.partner_matching import get_partner_filters, normalize_criteria
from connect.customer.doctype.customer_project.test_hiring import PROJECT_ANSWERS, make_buyer
from connect.customer.doctype.customer_project.test_partner_matching import make_listed_partner

BUYER = "questions.buyer@example.test"
COMPANY = "_Test Questions Co"
WITH_ERPNEXT = "_Test Questions ERPNext Partner"
WITH_HR = "_Test Questions HR Partner"


class TestProjectQuestions(IntegrationTestCase):
	"""Every entry point saves the same answers: the project's on the project, the company's on
	its Customer."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		make_buyer(BUYER, COMPANY)
		frappe.set_user(BUYER)

	def save(self, **answers):
		return save_project({**PROJECT_ANSWERS, **answers})

	def test_projects_are_named_after_the_company_and_numbered(self):
		names = [self.save()["project_name"] for _ in range(3)]
		base = f"Implementation for {COMPANY}"
		self.assertEqual(names, [base, f"{base} (2)", f"{base} (3)"])

	def test_a_deleted_draft_leaves_its_number_unused(self):
		self.save()
		second = self.save()["name"]
		self.save()
		delete_project(second)

		self.assertEqual(self.save()["project_name"], f"Implementation for {COMPANY} (4)")

	def test_company_answers_update_the_customer_for_the_next_project(self):
		self.save(company_size="51-200", industries=["Retail", "E-commerce"])

		customer = frappe.get_doc("Customer", COMPANY)
		self.assertEqual((customer.company_size, customer.get_industries()), ("51-200", ["Retail", "E-commerce"]))

	def test_every_question_must_be_answered(self):
		for question, message in (("regions", "where your partners"), ("apps", "apps"), ("problems", "solve")):
			with self.subTest(question), self.assertRaisesRegex(frappe.ValidationError, message):
				self.save(**{question: []})

	def test_systems_are_asked_only_when_not_on_spreadsheets(self):
		with self.assertRaisesRegex(frappe.ValidationError, "systems"):
			self.save(operations="outgrown_erp", systems=[])

		project = self.save(operations="spreadsheets", systems=["Tally"])
		self.assertEqual(project["systems"], [])

	def test_an_answer_outside_the_options_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "not one of the answers"):
			self.save(go_live="tomorrow")

	def test_edit_criteria_keeps_regions_and_work_mode_as_answers(self):
		project = self.save()["name"]
		criteria = {"countries": ["Germany"], "work": ["onsite"], "industries": ["Healthcare"], "tiers": ["Gold"]}

		saved = save_criteria(project, frappe.as_json(criteria))

		self.assertEqual((saved["regions"], saved["work_modes"]), (["Germany"], ["onsite"]))
		# Industries are the company's answer, so Edit criteria leaves them alone.
		self.assertEqual((saved["criteria"]["industries"], saved["criteria"]["tiers"]), (["Retail"], ["Gold"]))


class TestAppMatching(IntegrationTestCase):
	"""A partner gets the brief when they list at least one of the picked apps."""

	def setUp(self):
		self.addCleanup(frappe.db.rollback)
		for partner, app in ((WITH_ERPNEXT, "ERPNext"), (WITH_HR, "Frappe HR")):
			make_listed_partner(partner)
			doc = frappe.get_doc("Partner", partner)
			doc.set("apps", [{"app": app}])
			doc.save(ignore_permissions=True)

	def matching(self, apps):
		filters = get_partner_filters(normalize_criteria({"apps": apps}))
		found = frappe.get_all("Partner", filters=filters, pluck="name")
		return sorted(name for name in found if name in (WITH_ERPNEXT, WITH_HR))

	def test_any_one_picked_app_is_enough(self):
		self.assertEqual(self.matching(["ERPNext", "Frappe HR"]), sorted([WITH_ERPNEXT, WITH_HR]))
		self.assertEqual(self.matching(["Frappe HR"]), [WITH_HR])

	def test_an_app_no_partner_lists_matches_none(self):
		self.assertEqual(self.matching(["Helpdesk"]), [])
