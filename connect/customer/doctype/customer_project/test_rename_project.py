# Copyright (c) 2026
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.customer_project import rename_project
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_project

OWNER = "rename.owner@example.test"
STRANGER = "rename.stranger@example.test"


class TestRenameProject(IntegrationTestCase):
	"""The owner renames their project from its header; nobody else can."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		make_buyer(OWNER, "Rename Owner Co")
		make_buyer(STRANGER, "Rename Stranger Co")
		frappe.set_user(OWNER)
		self.project = make_project().name

	def rename(self, title, user=OWNER):
		frappe.set_user(user)
		return rename_project(self.project, title)

	def test_the_owner_renames_it(self):
		self.assertEqual(self.rename("  Warehouse barcode workflow ")["project_name"], "Warehouse barcode workflow")
		self.assertEqual(frappe.db.get_value("Customer Project", self.project, "project_name"), "Warehouse barcode workflow")

	def test_a_name_is_required(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Give your project a name"):
			self.rename("   ")

	def test_a_name_stays_short(self):
		self.assertEqual(len(self.rename("x" * 140)["project_name"]), 140)
		with self.assertRaisesRegex(frappe.ValidationError, "140 characters or fewer"):
			self.rename("x" * 141)

	def test_the_name_is_locked_once_a_hire_is_asked(self):
		frappe.db.set_value("Customer Project", self.project, "status", "Hiring")
		with self.assertRaisesRegex(frappe.ValidationError, "name stays as it is"):
			self.rename("Too late")

	def test_someone_else_cannot_rename_it(self):
		with self.assertRaises(frappe.PermissionError):
			self.rename("Mine now", user=STRANGER)
