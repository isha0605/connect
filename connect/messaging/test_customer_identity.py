# Copyright (c) 2026
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.api.messages import get_pinned_messages, search_messages
from connect.api.threads import get_my_threads, get_thread_member_profiles, get_thread_members, get_thread_messages
from connect.customer.doctype.customer_project.brief import send_brief
from connect.customer.doctype.customer_project.customer_project import set_quote_status
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.customer.doctype.project_quote.leads import get_lead
from connect.messaging.customer_identity import ANONYMOUS_USER, anonymous_company
from connect.messaging.doctype.connect_thread.connect_thread import open_contact_thread

PARTNER = "_Test Identity Partner"
OWNER = "identity.owner@example.test"
BUYER = "identity.buyer@example.test"
COMPANY = "Identity Buyer Co"


class TestCustomerIdentity(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		# Each test changes the shared thread (revealing it, say); start every test afresh.
		self.addCleanup(frappe.db.rollback)
		# The new-requirement email job runs at once in tests and commits; these tests check data, not mail.
		patch("connect.notifications.frappe.enqueue").start()
		self.addCleanup(patch.stopall)
		make_partner(PARTNER)
		make_partner_admin(PARTNER, OWNER)
		make_buyer(BUYER, COMPANY)

		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "Stock and expiry", "status": "Shared", "user": BUYER}
		).insert(ignore_permissions=True)
		project.db_set("user", BUYER)
		self.thread = send_brief(project, COMPANY, PARTNER)
		self.quote, self.lead = frappe.db.get_value("Project Quote", {"customer_project": project.name}, ["name", "lead"])
		self.message = frappe.get_doc(
			{"doctype": "Connect Message", "thread": self.thread, "sender": BUYER, "content": "We use Tally today"}
		).insert(ignore_permissions=True)

	def as_user(self, user):
		frappe.set_user(user)

	def my_thread(self):
		return next(t for t in get_my_threads() if t["name"] == self.thread)

	def test_a_brief_reaches_the_partner_from_an_anonymous_company(self):
		self.as_user(OWNER)
		thread = self.my_thread()
		self.assertEqual(thread["customer_name"], anonymous_company())
		self.assertIsNone(thread["customer"])
		self.assertEqual(thread["last_message_sender"], ANONYMOUS_USER)

		messages = get_thread_messages(self.thread)
		self.assertEqual({m.sender for m in messages}, {ANONYMOUS_USER})
		card = next(m for m in messages if m.message_type == "Requirement")
		self.assertNotIn("company_name", frappe.parse_json(card.content))

		self.assertNotIn(BUYER, [m["user"] for m in get_thread_members(self.thread)])
		self.assertNotIn(BUYER, [p["name"] for p in get_thread_member_profiles(self.thread)])
		self.assertEqual(get_lead(self.lead)["lead"]["company"], anonymous_company())

	def test_the_partner_cannot_read_the_customer_through_generic_reads(self):
		self.as_user(OWNER)
		senders = frappe.get_list("Connect Message", filters={"thread": self.thread}, pluck="sender")
		self.assertNotIn(BUYER, senders)
		self.assertFalse(frappe.has_permission("Connect Message", "read", doc=self.message.name))
		members = frappe.get_list("Connect Thread Member", filters={"thread": self.thread}, pluck="user")
		self.assertNotIn(BUYER, members)

	def test_search_and_pins_mask_the_customer(self):
		self.message.db_set({"is_pinned": 1, "pinned_by": BUYER})
		self.as_user(OWNER)
		results = search_messages("Tally", thread=self.thread)
		self.assertEqual([(r.sender, r.sender_full_name) for r in results], [(ANONYMOUS_USER, anonymous_company())])
		self.assertEqual(get_pinned_messages(self.thread)[0].pinned_by, ANONYMOUS_USER)

	def test_the_customer_still_sees_themselves(self):
		self.as_user(BUYER)
		self.assertIn(BUYER, {m.sender for m in get_thread_messages(self.thread)})
		self.assertEqual(self.my_thread()["is_customer_revealed"], 0)

	def test_interest_in_the_quote_reveals_the_customer(self):
		frappe.db.set_value("Project Quote", self.quote, "status", "Quoted")
		self.as_user(BUYER)
		set_quote_status(self.quote, "Interested")

		self.as_user(OWNER)
		self.assertEqual(self.my_thread()["customer_name"], COMPANY)
		self.assertIn(BUYER, {m.sender for m in get_thread_messages(self.thread)})
		self.assertEqual(get_lead(self.lead)["lead"]["contact"]["email"], BUYER)

	def test_contacting_a_partner_directly_reveals_the_customer(self):
		self.as_user(BUYER)
		open_contact_thread(COMPANY, PARTNER, BUYER)
		self.assertTrue(frappe.db.get_value("Connect Thread", self.thread, "is_customer_revealed"))
