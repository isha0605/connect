# Copyright (c) 2026, Isha and contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.roles import CUSTOMER_ROLE

ALICE = "_test_dm_alice@example.com"
BOB = "_test_dm_bob@example.com"
MALLORY = "_test_dm_mallory@example.com"


def make_customer_user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	frappe.get_doc("User", email).add_roles(CUSTOMER_ROLE)
	return email


def make_dm_thread(first, second):
	user_a, user_b = sorted([first, second])
	existing = frappe.db.get_value("Connect DM Thread", {"user_a": user_a, "user_b": user_b})
	if existing:
		return existing
	return frappe.get_doc({"doctype": "Connect DM Thread", "user_a": user_a, "user_b": user_b}).insert().name


def delete_dm_threads(first, second):
	for user_a, user_b in ((first, second), (second, first)):
		for name in frappe.get_all("Connect DM Thread", filters={"user_a": user_a, "user_b": user_b}, pluck="name"):
			frappe.delete_doc("Connect DM Thread", name, force=True)


class IntegrationTestConnectDMThread(IntegrationTestCase):
	"""A DM can only be opened by one of its two participants."""

	def setUp(self):
		for email in (ALICE, BOB, MALLORY):
			make_customer_user(email)
		delete_dm_threads(ALICE, BOB)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_participant_can_open_dm(self):
		frappe.set_user(ALICE)
		make_dm_thread(ALICE, BOB)

	def test_reversed_pair_is_stored_in_order(self):
		frappe.set_user(BOB)
		thread = frappe.get_doc({"doctype": "Connect DM Thread", "user_a": BOB, "user_b": ALICE}).insert()
		self.assertEqual((thread.user_a, thread.user_b), tuple(sorted([ALICE, BOB])))

	def test_reversed_duplicate_is_rejected(self):
		make_dm_thread(ALICE, BOB)
		frappe.set_user(BOB)
		with self.assertRaises(frappe.UniqueValidationError):
			frappe.get_doc({"doctype": "Connect DM Thread", "user_a": BOB, "user_b": ALICE}).insert()

	def test_outsider_cannot_open_dm_between_others(self):
		frappe.set_user(MALLORY)
		with self.assertRaises(frappe.PermissionError):
			make_dm_thread(ALICE, BOB)
