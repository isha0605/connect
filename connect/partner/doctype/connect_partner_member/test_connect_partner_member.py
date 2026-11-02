# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.permissions import _get_partner_owners
from connect.team import add_team_member, get_my_team, remove_team_member, set_team_member_access

PARTNER = "_Test Access Partner"
OTHER_PARTNER = "_Test Other Access Partner"
OWNER = "access.owner@example.test"
SALES = "access.sales@example.test"
OUTSIDER = "access.outsider@example.test"


def make_partner(partner_name):
	if not frappe.db.exists("Partner", partner_name):
		tier = next(t for t in frappe.get_meta("Partner").get_field("tier").options.split("\n") if t)
		frappe.get_doc({"doctype": "Partner", "partner_name": partner_name, "tier": tier, "country": "India"}).insert(
			ignore_permissions=True
		)


def make_member(partner, email, is_admin=0, access="Member"):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split(".")[1]}).insert(
			ignore_permissions=True
		)
	return frappe.get_doc(
		{"doctype": "Connect Partner Member", "partner": partner, "user": email, "is_admin": is_admin, "access": access}
	).insert(ignore_permissions=True)


class IntegrationTestConnectPartnerMember(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		make_partner(PARTNER)
		make_partner(OTHER_PARTNER)
		frappe.db.delete("Connect Partner Member", {"partner": ["in", [PARTNER, OTHER_PARTNER]]})
		self.owner = make_member(PARTNER, OWNER, is_admin=1)
		self.sales = make_member(PARTNER, SALES, access="Sales")
		self.outsider = make_member(OTHER_PARTNER, OUTSIDER, is_admin=1)

	def test_a_firm_can_have_several_owners(self):
		frappe.set_user(OWNER)
		set_team_member_access(self.sales.name, "Owner")

		self.assertEqual(_get_partner_owners(PARTNER), [OWNER, SALES])

	def test_an_owner_sets_sales_finance_or_member(self):
		frappe.set_user(OWNER)
		result = set_team_member_access(self.sales.name, "Finance")

		self.assertEqual(result["access_level"], "Finance")
		self.assertEqual(frappe.db.get_value("Connect Partner Member", self.sales.name, "is_admin"), 0)

	def test_the_team_list_shows_access_and_invited(self):
		frappe.set_user(OWNER)
		rows = {row.user: row for row in get_my_team()}

		self.assertEqual(rows[OWNER].access_level, "Owner")
		self.assertEqual(rows[SALES].access_level, "Sales")
		self.assertTrue(rows[SALES].is_invited)

	def test_a_non_owner_cannot_change_access(self):
		frappe.set_user(SALES)
		with self.assertRaises(frappe.PermissionError):
			set_team_member_access(self.owner.name, "Member")

	def test_an_owner_cannot_change_another_firms_member(self):
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.PermissionError):
			set_team_member_access(self.outsider.name, "Member")

	def test_the_last_owner_cannot_step_down(self):
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.ValidationError):
			set_team_member_access(self.owner.name, "Member")

	def test_the_last_owner_cannot_be_removed(self):
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.ValidationError):
			remove_team_member(self.owner.name)

	def test_a_removed_owner_stops_being_an_owner(self):
		frappe.set_user(OWNER)
		set_team_member_access(self.sales.name, "Owner")
		remove_team_member(self.sales.name)

		self.assertEqual(_get_partner_owners(PARTNER), [OWNER])
		self.assertEqual(frappe.db.get_value("Connect Partner Member", self.sales.name, "is_admin"), 0)

	def test_an_invite_sets_name_and_access(self):
		frappe.set_user(OWNER)
		add_team_member("access.new@example.test", full_name="New Person", access_level="Sales")

		member = frappe.get_doc("Connect Partner Member", {"partner": PARTNER, "user": "access.new@example.test"})
		self.assertEqual((member.is_admin, member.access), (0, "Sales"))
		self.assertEqual(frappe.db.get_value("User", "access.new@example.test", "first_name"), "New Person")

	def test_a_removed_person_can_be_invited_again(self):
		frappe.set_user(OWNER)
		remove_team_member(self.sales.name)
		add_team_member(SALES, full_name="Back Again", access_level="Finance")

		member = frappe.get_doc("Connect Partner Member", self.sales.name)
		self.assertEqual((member.is_removed, member.removed_on, member.access), (0, None, "Finance"))
		self.assertIn(SALES, [row.user for row in get_my_team() if not row.is_removed])

	def test_a_current_member_cannot_be_invited_twice(self):
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.ValidationError):
			add_team_member(SALES)
