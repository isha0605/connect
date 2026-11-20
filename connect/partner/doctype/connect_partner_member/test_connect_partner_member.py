# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer
from connect.messaging.doctype.connect_thread.connect_thread import ensure_partner_member, get_or_open_thread
from connect.partner.doctype.connect_partner_member.connect_partner_member import CUSTOMER_ACCESS, LEAD_ACCESS
from connect.patches.set_one_owner_per_partner import split_owners
from connect.permissions import _get_partner_admins, _has_partner_access
from connect.team import add_team_member, get_my_team, remove_team_member, set_team_member_access

PARTNER = "_Test Access Partner"
OTHER_PARTNER = "_Test Other Access Partner"
OWNER = "access.owner@example.test"
ADMIN = "access.admin@example.test"
SALES = "access.sales@example.test"
OUTSIDER = "access.outsider@example.test"
BUYER = "access.buyer@example.test"
CUSTOMER = "_Test Access Customer"


def make_partner(partner_name):
	"""An approved partner: only those invite a team."""
	if not frappe.db.exists("Partner", partner_name):
		tier = "Gold"
		frappe.get_doc({"doctype": "Partner", "partner_name": partner_name, "tier": tier, "country": "India"}).insert(
			ignore_permissions=True
		)
	frappe.db.set_value("Partner", partner_name, "verification_status", "Verified")


def make_member(partner, email, access="Member"):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split(".")[1]}).insert(
			ignore_permissions=True
		)
	return frappe.get_doc(
		{"doctype": "Connect Partner Member", "partner": partner, "user": email, "access": access}
	).insert(ignore_permissions=True)


def access_of(member) -> str:
	return frappe.db.get_value("Connect Partner Member", member.name, "access")


class IntegrationTestConnectPartnerMember(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		make_partner(PARTNER)
		make_partner(OTHER_PARTNER)
		frappe.db.delete("Connect Partner Member", {"partner": ["in", [PARTNER, OTHER_PARTNER]]})
		self.owner = make_member(PARTNER, OWNER, access="Owner")
		self.admin = make_member(PARTNER, ADMIN, access="Admin")
		self.sales = make_member(PARTNER, SALES, access="Sales")
		self.outsider = make_member(OTHER_PARTNER, OUTSIDER, access="Owner")

	def test_a_firm_has_one_owner(self):
		with self.assertRaises(frappe.ValidationError):
			make_member(PARTNER, "access.second.owner@example.test", access="Owner")

	def test_a_transfer_makes_the_old_owner_an_admin(self):
		frappe.set_user(OWNER)
		set_team_member_access(self.sales.name, "Owner")

		self.assertEqual((access_of(self.sales), access_of(self.owner)), ("Owner", "Admin"))
		self.assertEqual(_get_partner_admins(PARTNER), [SALES, OWNER, ADMIN])

	def test_the_owner_and_admins_see_leads_and_customers(self):
		for user in (OWNER, ADMIN):
			self.assertTrue(_has_partner_access(PARTNER, user, LEAD_ACCESS))
			self.assertTrue(_has_partner_access(PARTNER, user, CUSTOMER_ACCESS))

	def test_an_admin_manages_sales_finance_and_members(self):
		frappe.set_user(ADMIN)
		result = set_team_member_access(self.sales.name, "Finance")

		self.assertEqual(result["access_level"], "Finance")

	def test_only_the_owner_makes_changes_or_removes_an_admin(self):
		frappe.set_user(ADMIN)
		for member, level in ((self.sales, "Admin"), (self.admin, "Member"), (self.sales, "Owner")):
			with self.assertRaises(frappe.PermissionError):
				set_team_member_access(member.name, level)
		with self.assertRaises(frappe.PermissionError):
			remove_team_member(self.admin.name)

		frappe.set_user(OWNER)
		set_team_member_access(self.sales.name, "Admin")
		remove_team_member(self.admin.name)
		self.assertEqual(_get_partner_admins(PARTNER), [OWNER, SALES])

	def test_a_sales_member_cannot_change_access(self):
		frappe.set_user(SALES)
		with self.assertRaises(frappe.PermissionError):
			set_team_member_access(self.sales.name, "Finance")

	def test_an_owner_cannot_change_another_firms_member(self):
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.PermissionError):
			set_team_member_access(self.outsider.name, "Member")

	def test_the_owner_cannot_step_down_or_be_removed(self):
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.ValidationError):
			set_team_member_access(self.owner.name, "Admin")
		with self.assertRaises(frappe.ValidationError):
			remove_team_member(self.owner.name)

	def test_a_removed_admin_keeps_no_access(self):
		frappe.set_user(OWNER)
		remove_team_member(self.admin.name)

		self.assertEqual(access_of(self.admin), "Member")
		self.assertNotIn(ADMIN, _get_partner_admins(PARTNER))

	def test_the_team_list_shows_access_and_invited(self):
		frappe.set_user(OWNER)
		rows = get_my_team()
		by_user = {row.user: row for row in rows}

		self.assertEqual([row.user for row in rows], [OWNER, ADMIN, SALES])
		self.assertEqual((by_user[ADMIN].access_level, by_user[ADMIN].is_admin), ("Admin", True))
		self.assertEqual((by_user[SALES].access_level, by_user[SALES].is_admin), ("Sales", False))
		self.assertTrue(by_user[SALES].is_invited)

	def test_an_invite_sets_name_and_access(self):
		frappe.set_user(OWNER)
		add_team_member("access.new@example.test", full_name="New Person", access_level="Admin")

		member = frappe.get_doc("Connect Partner Member", {"partner": PARTNER, "user": "access.new@example.test"})
		self.assertEqual(member.access, "Admin")
		self.assertEqual(frappe.db.get_value("User", "access.new@example.test", "first_name"), "New Person")

	def test_a_partner_frappe_has_not_approved_cannot_invite(self):
		frappe.db.set_value("Partner", PARTNER, "verification_status", "Pending Review")
		frappe.set_user(OWNER)
		with self.assertRaisesRegex(frappe.PermissionError, "once Frappe approves"):
			add_team_member("access.early@example.test", access_level="Member")
		self.assertFalse(frappe.db.exists("Connect Partner Member", {"user": "access.early@example.test"}))

	def test_an_invite_cannot_make_an_owner_and_only_the_owner_adds_an_admin(self):
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.ValidationError):
			add_team_member("access.new.owner@example.test", access_level="Owner")

		frappe.set_user(ADMIN)
		with self.assertRaises(frappe.PermissionError):
			add_team_member("access.new.admin@example.test", access_level="Admin")
		self.assertFalse(frappe.db.exists("User", "access.new.admin@example.test"))

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

	def test_the_owner_hands_over_the_firm_from_a_chat(self):
		make_buyer(BUYER, CUSTOMER)
		thread = get_or_open_thread(CUSTOMER, PARTNER, BUYER)
		ensure_partner_member(thread, SALES, OWNER)
		thread_member = frappe.get_doc("Connect Thread Member", {"thread": thread, "user": SALES, "is_removed": 0})

		with self.assertRaises(frappe.PermissionError):
			thread_member.make_admin(ADMIN)
		thread_member.make_admin(OWNER)

		self.assertEqual((access_of(self.sales), access_of(self.owner)), ("Owner", "Admin"))


class UnitTestSetOneOwnerPerPartner(UnitTestCase):
	def test_the_earliest_owner_stays_and_the_rest_become_admins(self):
		owners = [
			{"name": "a1", "company": "A"},
			{"name": "b1", "company": "B"},
			{"name": "a2", "company": "A"},
			{"name": "a3", "company": "A"},
		]

		self.assertEqual(split_owners(owners), (["a1", "b1"], ["a2", "a3"]))
