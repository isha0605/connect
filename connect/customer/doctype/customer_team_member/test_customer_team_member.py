# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.permissions import _get_customer_owner, _is_customer_admin
from connect.team import add_team_member, get_my_team, remove_team_member, set_team_member_access

CUSTOMER = "_Test Roles Customer"
OWNER = "roles.owner@example.test"
ADMIN = "roles.admin@example.test"
MEMBER = "roles.member@example.test"


def make_member(email, access="Member"):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split(".")[1]}).insert(
			ignore_permissions=True
		)
	return frappe.get_doc(
		{"doctype": "Customer Team Member", "customer": CUSTOMER, "user": email, "access": access}
	).insert(ignore_permissions=True)


def access_of(member) -> str:
	return frappe.db.get_value("Customer Team Member", member.name, "access")


class IntegrationTestCustomerTeamMember(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		if not frappe.db.exists("Customer", CUSTOMER):
			frappe.get_doc({"doctype": "Customer", "customer_name": CUSTOMER}).insert(ignore_permissions=True)
		frappe.db.delete("Customer Team Member", {"customer": CUSTOMER})
		self.owner = make_member(OWNER, access="Owner")
		self.admin = make_member(ADMIN, access="Admin")
		self.member = make_member(MEMBER)

	def test_a_company_has_one_owner(self):
		with self.assertRaises(frappe.ValidationError):
			make_member("roles.second.owner@example.test", access="Owner")

	def test_a_transfer_makes_the_old_owner_an_admin(self):
		frappe.set_user(OWNER)
		set_team_member_access(self.member.name, "Owner")

		self.assertEqual((access_of(self.member), access_of(self.owner)), ("Owner", "Admin"))
		self.assertEqual(_get_customer_owner(CUSTOMER), MEMBER)

	def test_only_the_owner_makes_or_removes_an_admin(self):
		frappe.set_user(ADMIN)
		with self.assertRaises(frappe.PermissionError):
			set_team_member_access(self.member.name, "Admin")
		with self.assertRaises(frappe.PermissionError):
			add_team_member("roles.new.admin@example.test", access_level="Admin")

		frappe.set_user(OWNER)
		set_team_member_access(self.member.name, "Admin")
		self.assertEqual(access_of(self.member), "Admin")

	def test_a_member_cannot_change_the_team(self):
		frappe.set_user(MEMBER)
		with self.assertRaises(frappe.PermissionError):
			add_team_member("roles.new@example.test")

	def test_a_removed_admin_is_no_longer_an_admin(self):
		frappe.set_user(OWNER)
		remove_team_member(self.admin.name)

		self.assertFalse(_is_customer_admin(CUSTOMER, ADMIN))

	def test_a_customer_has_no_sales_or_finance(self):
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.ValidationError):
			add_team_member("roles.sales@example.test", access_level="Sales")

	def test_the_team_list_puts_the_owner_first(self):
		frappe.set_user(MEMBER)
		rows = get_my_team()

		self.assertEqual([(row.user, row.access_level) for row in rows], [(OWNER, "Owner"), (ADMIN, "Admin"), (MEMBER, "Member")])
