# Copyright (c) 2026
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.customer_project import share_requirements
from connect.customer.doctype.customer_project.partner_matching import get_partner_filters, normalize_criteria
from connect.customer.doctype.customer_project.test_hiring import (
	PROJECT_ANSWERS,
	make_buyer,
	make_partner_admin,
	make_project,
)
from connect.customer.doctype.customer_project.test_partner_matching import make_listed_partner

BUYER = "questions.buyer@example.test"
COMPANY = "_Test Questions Co"
WITH_ERPNEXT = "_Test Questions ERPNext Partner"
WITH_HR = "_Test Questions HR Partner"
MATCHING = "_Test Questions Matching Partner"


def make_matching_partner(name=MATCHING):
	"""A listed partner, with an Owner, that PROJECT_ANSWERS reaches."""
	make_listed_partner(name)
	if not frappe.db.exists("Delivery Mode", "Remote"):
		frappe.get_doc({"doctype": "Delivery Mode", "delivery_mode": "Remote"}).insert(
			ignore_permissions=True
		)
	doc = frappe.get_doc("Partner", name)
	doc.set("industries", [{"industry": "Retail"}])
	doc.set("apps", [{"app": "ERPNext"}])
	doc.set("delivery_options", [{"delivery_mode": "Remote"}])
	doc.save(ignore_permissions=True)
	make_partner_admin(name, "questions.partner.admin@example.test")
	return name


class TestProjectQuestions(IntegrationTestCase):
	"""Every entry point saves the same answers: the project's on the project, the company's on
	its Customer."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		make_buyer(BUYER, COMPANY)
		frappe.set_user(BUYER)

	def test_projects_are_named_after_the_company_and_numbered(self):
		names = [make_project().project_name for _ in range(3)]
		base = f"Implementation for {COMPANY}"
		self.assertEqual(names, [base, f"{base} (2)", f"{base} (3)"])

	def test_a_deleted_project_below_the_highest_leaves_its_number_unused(self):
		make_project()
		second = make_project().name
		make_project()
		frappe.delete_doc("Customer Project", second, ignore_permissions=True)

		self.assertEqual(make_project().project_name, f"Implementation for {COMPANY} (4)")

	def test_company_answers_update_the_customer_for_the_next_project(self):
		make_project(company_size="51-200", industries=["Retail", "E-commerce"])

		customer = frappe.get_doc("Customer", COMPANY)
		self.assertEqual(
			(customer.company_size, customer.get_industries()), ("51-200", ["Retail", "E-commerce"])
		)

	def test_answers_left_out_keep_what_was_saved(self):
		doc = make_project()

		doc.set_answers({"budget": "Over ₹40 lakh"})

		self.assertEqual(
			(doc.budget, doc.go_live, [row.app for row in doc.apps]),
			("Over ₹40 lakh", "one_to_three_months", ["ERPNext"]),
		)
		customer = frappe.get_doc("Customer", COMPANY)
		self.assertEqual((customer.company_size, customer.get_industries()), ("11-50", ["Retail"]))

	def test_every_question_must_be_answered(self):
		for question, message in (
			("regions", "where your partners"),
			("apps", "apps"),
			("problems", "solve"),
		):
			with self.subTest(question), self.assertRaisesRegex(frappe.ValidationError, message):
				make_project(**{question: []})

	def test_systems_are_asked_only_when_not_on_spreadsheets(self):
		with self.assertRaisesRegex(frappe.ValidationError, "systems"):
			make_project(operations="outgrown_erp", systems=[])

		project = make_project(operations="spreadsheets", systems=["Tally"])
		self.assertEqual(frappe.parse_json(project.systems), [])

	def test_an_answer_outside_the_options_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "not one of the answers"):
			make_project(go_live="tomorrow")

	def test_share_dialog_extras_are_kept_beside_the_answers(self):
		project = make_project(criteria={"cities": ["Pune"], "tiers": ["Gold"], "industries": ["Healthcare"]})

		self.assertEqual(frappe.parse_json(project.criteria), {"cities": ["Pune"], "tiers": ["Gold"]})


class TestShareRequirements(IntegrationTestCase):
	"""New project: saved and sent to every matching partner in one go, or not saved at all."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		make_buyer(BUYER, COMPANY)
		make_matching_partner()

	def share(self, **answers):
		frappe.set_user(BUYER)
		try:
			return share_requirements({**PROJECT_ANSWERS, **answers})
		finally:
			frappe.set_user("Administrator")

	def test_a_new_project_goes_to_the_partners_it_matches(self):
		project = self.share()

		self.assertEqual(project["status"], "Shared")
		self.assertTrue(
			frappe.db.exists("Project Quote", {"customer_project": project["name"], "partner": MATCHING})
		)

	def test_with_no_partner_to_send_to_nothing_is_saved(self):
		before = frappe.db.count("Customer Project", {"user": BUYER})
		with self.assertRaisesRegex(frappe.ValidationError, "No partners match"):
			self.share(regions=["_Test Nowhere"])
		self.assertEqual(frappe.db.count("Customer Project", {"user": BUYER}), before)


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


class TestWhoChangesCompanyFacts(IntegrationTestCase):
	"""Any member may fill in the company's blank facts; only the Owner or an Admin changes them."""

	MEMBER = "questions.member@example.test"

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		make_buyer(BUYER, COMPANY)
		make_buyer(self.MEMBER, COMPANY)
		frappe.db.set_value("Customer Team Member", {"user": BUYER}, "access", "Owner")
		frappe.db.set_value("Customer Team Member", {"user": self.MEMBER}, "access", "Member")
		customer = frappe.get_doc("Customer", COMPANY)
		customer.company_size = ""
		customer.set("industries", [])
		customer.save(ignore_permissions=True)

	def save_as(self, user, **answers):
		frappe.set_user(user)
		try:
			return make_project(**answers)
		finally:
			frappe.set_user("Administrator")

	def test_a_member_fills_in_blank_facts(self):
		self.save_as(self.MEMBER)
		self.assertEqual(frappe.db.get_value("Customer", COMPANY, "company_size"), "11-50")

	def test_a_member_cannot_change_set_facts(self):
		self.save_as(self.MEMBER)
		with self.assertRaises(frappe.PermissionError):
			self.save_as(self.MEMBER, company_size="500+")
		with self.assertRaises(frappe.PermissionError):
			self.save_as(self.MEMBER, industries=["Healthcare"])

	def test_the_owner_changes_them(self):
		self.save_as(self.MEMBER)
		self.save_as(BUYER, company_size="500+")
		self.assertEqual(frappe.db.get_value("Customer", COMPANY, "company_size"), "500+")

	def test_settings_follow_the_same_rule(self):
		from connect.customer.doctype.customer.customer import save_my_company_details

		self.save_as(self.MEMBER)
		frappe.set_user(self.MEMBER)
		details = {
			"country": "Kenya",
			"company_size": "11-50",
			"industries": ["Retail"],
			"current_system": "Tally",
		}
		saved = save_my_company_details(details)
		self.assertEqual(
			(saved["country"], saved["current_system"], saved["can_change_facts"]), ("Kenya", "Tally", False)
		)
		with self.assertRaises(frappe.PermissionError):
			save_my_company_details({**details, "industries": ["Healthcare"]})
