# Copyright (c) 2026, Isha and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.messaging.doctype.connect_thread_member.connect_thread_member import get_unread_counts, mark_read
from connect.starter_packs.doctype.starter_pack_order.test_starter_pack_order import make_user

READER = "_test_unread_reader@example.com"
OTHER = "_test_unread_other@example.com"


class IntegrationTestConnectThreadMember(IntegrationTestCase):
	"""The sidebar's unread badge: messages from others since the member last read the thread."""

	def setUp(self):
		patch("connect.notifications.notify_thread_members").start()
		patch("connect.crm_integration.queue_crm_lead_sync").start()
		make_user(READER)
		make_user(OTHER)
		self.thread = make_thread(customer_name=f"_Test Unread {self._testMethodName}")

	def tearDown(self):
		patch.stopall()

	def test_counts_only_others_messages_since_last_read(self):
		read_up_to = post(self.thread, OTHER)
		add_member(self.thread, READER, last_read_at=read_up_to)
		post(self.thread, OTHER)
		post(self.thread, READER)

		self.assertEqual(get_unread_counts([self.thread], READER), {self.thread: 1})

	def test_a_removed_member_stops_counting_at_removal(self):
		member = add_member(self.thread, READER)
		post(self.thread, OTHER)
		remove(member, removed_on=post(self.thread, OTHER))
		post(self.thread, OTHER)

		self.assertEqual(get_unread_counts([self.thread], READER), {self.thread: 2})

	def test_a_re_added_member_counts_from_their_active_membership(self):
		old_member = add_member(self.thread, READER)
		remove(old_member, removed_on=post(self.thread, OTHER))
		read_up_to = post(self.thread, OTHER)
		add_member(self.thread, READER, last_read_at=read_up_to)
		post(self.thread, OTHER)

		self.assertEqual(get_unread_counts([self.thread], READER), {self.thread: 1})

	def test_reading_clears_the_badge(self):
		add_member(self.thread, READER)
		post(self.thread, OTHER)
		mark_read(self.thread, READER)

		self.assertEqual(get_unread_counts([self.thread], READER), {})

	def test_reading_leaves_a_removed_membership_frozen(self):
		member = add_member(self.thread, READER)
		remove(member, removed_on=post(self.thread, OTHER))
		mark_read(self.thread, READER)

		self.assertIsNone(frappe.db.get_value("Connect Thread Member", member.name, "last_read_at"))


def make_thread(customer_name):
	"""A fresh thread per test: the class only rolls back once all its tests have run."""
	partner = "_Test Unread Partner"
	if not frappe.db.exists("Partner", partner):
		frappe.get_doc({"doctype": "Partner", "partner_name": partner, "tier": "Gold", "country": "India"}).insert(
			ignore_permissions=True
		)
	customer = frappe.get_doc({"doctype": "Customer", "customer_name": customer_name}).insert(ignore_permissions=True)
	return (
		frappe.get_doc({"doctype": "Connect Thread", "customer": customer.name, "partner": partner})
		.insert(ignore_permissions=True)
		.name
	)


def add_member(thread, user, last_read_at=None):
	return frappe.get_doc(
		{
			"doctype": "Connect Thread Member",
			"thread": thread,
			"user": user,
			"side": "Customer",
			"added_by": "Administrator",
			"last_read_at": last_read_at,
		}
	).insert(ignore_permissions=True)


def remove(member, removed_on):
	member.is_removed = 1
	member.removed_on = removed_on
	member.save(ignore_permissions=True)


def post(thread, sender):
	"""Posts a message and returns its creation time, to use as a read or removal point."""
	message = frappe.get_doc(
		{"doctype": "Connect Message", "thread": thread, "sender": sender, "content": "hello"}
	).insert(ignore_permissions=True)
	return message.creation
