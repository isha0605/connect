# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.permissions import reset_perms, setup_custom_perms
from frappe.tests import IntegrationTestCase

from connect.patches.give_partner_staff_roles_custom_permissions import PARTNER_DOCTYPES
from connect.patches.give_partner_staff_roles_custom_permissions import execute as copy_to_custom_perms
from connect.roles import PARTNER_MANAGER_ROLE, STAFF_ROLE

MANAGER = "partner.manager.role@example.test"
STAFF = "staff.role@example.test"
# Customers' own words and system-written rows stay read-only for Partner Managers.
READ_ONLY_FOR_MANAGERS = ("Partner Review", "Partner Chat Reply")


def make_staff_user(email, role):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Staff", "user_type": "System User"}).insert(
			ignore_permissions=True
		)
	frappe.get_doc("User", email).add_roles(role)


def can(user, doctype, right):
	return frappe.has_permission(doctype, right, user=user)


class IntegrationTestStaffRoles(IntegrationTestCase):
	def setUp(self):
		make_staff_user(MANAGER, PARTNER_MANAGER_ROLE)
		make_staff_user(STAFF, STAFF_ROLE)

	def test_partner_manager_reads_and_edits_every_partner_doctype(self):
		for doctype in PARTNER_DOCTYPES:
			self.assertTrue(can(MANAGER, doctype, "read"), doctype)
			self.assertEqual(can(MANAGER, doctype, "write"), doctype not in READ_ONLY_FOR_MANAGERS, doctype)
			self.assertFalse(can(MANAGER, doctype, "delete"), doctype)

	def test_partner_manager_approves_applications_and_moderates_reviews(self):
		for doctype in ("Partner Application", "Certificate Application", "Partner Review"):
			self.assertTrue(can(MANAGER, doctype, "review"), doctype)

	def test_staff_only_reads_partner_doctypes(self):
		for doctype in PARTNER_DOCTYPES:
			self.assertTrue(can(STAFF, doctype, "read"), doctype)
			self.assertFalse(can(STAFF, doctype, "write"), doctype)
			self.assertFalse(can(STAFF, doctype, "review"), doctype)

	def test_a_site_with_saved_permissions_gets_the_staff_roles_from_the_patch(self):
		setup_custom_perms("Partner Lead")
		self.addCleanup(reset_perms, "Partner Lead")
		frappe.db.delete("Custom DocPerm", {"parent": "Partner Lead", "role": ["in", (PARTNER_MANAGER_ROLE, STAFF_ROLE)]})
		frappe.clear_cache(doctype="Partner Lead")
		self.assertFalse(can(STAFF, "Partner Lead", "read"))

		copy_to_custom_perms()
		self.assertTrue(can(STAFF, "Partner Lead", "read"))
		self.assertTrue(can(MANAGER, "Partner Lead", "write"))
