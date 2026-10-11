# Copyright (c) 2026, Isha and contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.messaging.doctype.connect_dm_thread.test_connect_dm_thread import (
	ALICE,
	BOB,
	MALLORY,
	make_customer_user,
	make_dm_thread,
)


def post(thread, sender):
	return frappe.get_doc(
		{"doctype": "Connect DM Message", "dm_thread": thread, "sender": sender, "message_type": "Text", "content": "hi"}
	).insert()


class IntegrationTestConnectDMMessage(IntegrationTestCase):
	"""Only the two people in a DM may post into it, including through the raw resource API."""

	def setUp(self):
		for email in (ALICE, BOB, MALLORY):
			make_customer_user(email)
		self.thread = make_dm_thread(ALICE, BOB)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_participant_can_post(self):
		frappe.set_user(ALICE)
		post(self.thread, ALICE)

	def test_outsider_cannot_post(self):
		frappe.set_user(MALLORY)
		with self.assertRaises(frappe.PermissionError):
			post(self.thread, MALLORY)

	def test_participant_cannot_post_as_the_other(self):
		frappe.set_user(ALICE)
		with self.assertRaises(frappe.PermissionError):
			post(self.thread, BOB)
