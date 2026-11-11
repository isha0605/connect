# Copyright (c) 2026
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.account import get_my_context
from connect.api.messages import search_messages
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.messaging.doctype.connect_thread.connect_thread import ensure_partner_member, get_or_open_thread
from connect.partner.doctype.connect_partner_member.connect_partner_member import (
	get_current_membership,
	get_current_partners,
	list_my_partners,
	switch_partner,
)
from connect.permissions import _check_can_read, _is_partner_admin
from connect.roles import PARTNER_ROLE

FIRST = "_Test Switch First Partner"
SECOND = "_Test Switch Second Partner"
OTHER = "_Test Switch Other Partner"
WORKER = "switch.worker@example.test"
SECOND_OWNER = "switch.second.owner@example.test"
OTHER_OWNER = "switch.other.owner@example.test"
BUYER = "switch.buyer@example.test"
CUSTOMER = "_Test Switch Customer"
SEARCH_WORD = "switchsearchword"


class IntegrationTestSwitchPartner(IntegrationTestCase):
	"""A person on two partner teams works for one firm at a time: its pages, access and chats."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		for partner in (FIRST, SECOND, OTHER):
			make_partner(partner)
		make_partner_admin(SECOND, SECOND_OWNER)
		make_partner_admin(OTHER, OTHER_OWNER)
		# FIRST before SECOND, so SECOND is the newest membership.
		add_member(FIRST, WORKER, is_admin=1)
		add_member(SECOND, WORKER, access="Sales")
		frappe.get_doc("User", WORKER).add_roles(PARTNER_ROLE)
		frappe.delete_doc("Connect User Settings", WORKER, force=True, ignore_missing=True)

		make_buyer(BUYER, CUSTOMER)
		self.first_thread = get_or_open_thread(CUSTOMER, FIRST, BUYER)
		self.second_thread = get_or_open_thread(CUSTOMER, SECOND, BUYER)
		self.other_thread = get_or_open_thread(CUSTOMER, OTHER, BUYER)
		ensure_partner_member(self.second_thread, WORKER, SECOND_OWNER)
		add_message(self.first_thread, SEARCH_WORD)

	def test_the_newest_membership_is_current_until_a_switch(self):
		self.assertEqual(get_current_membership(WORKER).partner, SECOND)

		firms = {row["partner"]: row for row in list_my_partners(WORKER)}
		self.assertEqual(firms[FIRST]["access_level"], "Owner")
		self.assertEqual(firms[SECOND]["access_level"], "Sales")
		self.assertTrue(firms[SECOND]["is_current"])

	def test_switching_changes_the_firm_and_the_access_level(self):
		switch_partner(WORKER, FIRST)
		frappe.set_user(WORKER)

		partner = get_my_context()["partner"]
		self.assertEqual(partner["partner"], FIRST)
		self.assertEqual(partner["access_level"], "Owner")
		self.assertFalse(_is_partner_admin(SECOND, WORKER))

	def test_cannot_switch_to_a_firm_you_are_not_on(self):
		with self.assertRaises(frappe.PermissionError):
			switch_partner(WORKER, OTHER)

	def test_chats_and_search_follow_the_current_firm(self):
		switch_partner(WORKER, FIRST)
		frappe.set_user(WORKER)
		self.assertEqual(visible_threads(), {self.first_thread})
		self.assertTrue(search_messages(SEARCH_WORD))

		switch_partner(WORKER, SECOND)

		self.assertEqual(visible_threads(), {self.second_thread})
		self.assertFalse(search_messages(SEARCH_WORD))
		with self.assertRaisesRegex(frappe.PermissionError, "Switch to that company"):
			_check_can_read(self.first_thread, WORKER)

	def test_a_guest_in_another_firms_chat_keeps_it(self):
		ensure_partner_member(self.other_thread, WORKER, OTHER_OWNER)
		frappe.set_user(WORKER)

		self.assertIn(self.other_thread, visible_threads(partners=(OTHER,)))
		_check_can_read(self.other_thread, WORKER)

	def test_leaving_a_firm_keeps_its_chats_readable_and_falls_back(self):
		switch_partner(WORKER, FIRST)
		member = frappe.db.get_value("Connect Partner Member", {"partner": FIRST, "user": WORKER})
		frappe.db.set_value("Connect Partner Member", member, {"is_removed": 1, "is_admin": 0})

		self.assertEqual(get_current_membership(WORKER).partner, SECOND)
		_check_can_read(self.first_thread, WORKER)

	def test_batched_lookup_matches_the_single_one(self):
		switch_partner(WORKER, FIRST)

		self.assertEqual(get_current_partners([WORKER, SECOND_OWNER]), {WORKER: FIRST, SECOND_OWNER: SECOND})


def add_member(partner, user, access=None, is_admin=0):
	"""Adds the user to the partner's team, or restores their membership as given."""
	if not frappe.db.exists("User", user):
		frappe.get_doc({"doctype": "User", "email": user, "first_name": "Member"}).insert(ignore_permissions=True)
	values = {"is_removed": 0, "is_admin": is_admin, "access": access}
	member = frappe.db.get_value("Connect Partner Member", {"partner": partner, "user": user})
	if member:
		frappe.db.set_value("Connect Partner Member", member, values)
		return
	frappe.get_doc({"doctype": "Connect Partner Member", "partner": partner, "user": user, **values}).insert(
		ignore_permissions=True
	)


def add_message(thread, content):
	if not frappe.db.exists("Connect Message", {"thread": thread, "content": content}):
		frappe.get_doc(
			{"doctype": "Connect Message", "thread": thread, "sender": BUYER, "content": content, "message_type": "Text"}
		).insert(ignore_permissions=True)


def visible_threads(partners=(FIRST, SECOND)):
	"""The test threads of `partners` the session user can list, as the Messaging sidebar lists them."""
	filters = {"customer": CUSTOMER, "partner": ["in", partners]}
	return set(frappe.get_list("Connect Thread", filters=filters, pluck="name"))
