# Copyright (c) 2026
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.api.contact import start_partner_thread
from connect.api.threads import get_my_threads
from connect.customer.doctype.starter_pack_order.implementation import (
	hand_over,
	hand_over_waiting_orders,
	post_opening_message,
)
from connect.customer.doctype.starter_pack_order.starter_pack_order import (
	PAYMENT_HOOK_FLAG,
	get_my_projects,
	get_order,
)
from connect.customer.doctype.starter_pack_order.test_starter_pack_order import make_order, make_pack, make_user
from connect.partner.consultants import on_user_update, sync_consultant
from connect.roles import CONSULTANT_ROLE, PARTNER_ROLE
from connect.utils import get_my_context

NOTIFY = "frappe.desk.doctype.notification_log.notification_log.enqueue_create_notification"
SETTINGS = "Starter Pack Settings"
FRAPPE = "_Test Frappe"
FRAPPE_ADMIN = "_test_frappe_admin@example.com"
ONE = "_test_consultant_one@example.com"
TWO = "_test_consultant_two@example.com"


def make_consultant(email, full_name):
	"""A User given the Frappe Consultant role, set up as the role's hook sets them up."""
	if not frappe.db.exists("User", email):
		first, last = full_name.split(" ", 1)
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": first, "last_name": last, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	frappe.get_doc("User", email).add_roles(CONSULTANT_ROLE)
	sync_consultant(email)
	return email


def take_role_away(email):
	frappe.get_doc("User", email).remove_roles(CONSULTANT_ROLE)
	sync_consultant(email)


def thread_members(thread):
	return set(
		frappe.get_all("Connect Thread Member", filters={"thread": thread, "is_removed": 0}, pluck="user")
	)


class IntegrationTestFrappeConsultants(IntegrationTestCase):
	"""Frappe delivers every Starter Pack; its consultants take the orders in turn, each with
	their own thread with the buyer."""

	def setUp(self):
		# Only this class's consultants take part; the class's rollback puts the site's back.
		frappe.db.set_value("Frappe Consultant", {"name": ["not in", [ONE, TWO]]}, "enabled", 0)
		if not frappe.db.exists("Partner", FRAPPE):
			frappe.get_doc({"doctype": "Partner", "partner_name": FRAPPE, "tier": "Gold", "country": "India"}).insert(
				ignore_permissions=True
			)
		make_user(FRAPPE_ADMIN)
		if not frappe.db.exists("Connect Partner Member", {"partner": FRAPPE, "user": FRAPPE_ADMIN}):
			frappe.get_doc(
				{"doctype": "Connect Partner Member", "partner": FRAPPE, "user": FRAPPE_ADMIN, "is_admin": 1}
			).insert(ignore_permissions=True)
		frappe.db.set_single_value(
			SETTINGS,
			{
				"implementation_partner": FRAPPE,
				"auto_assign_partners": 0,
				"rr_last_consultant": "",
				"rr_last_consultant_sequence": 0,
				"gst_rate": 18,
			},
		)
		self.pack = make_pack("_test_pack_a", 10000, 5)
		self.notify = patch(NOTIFY).start()
		patch("frappe.log_error").start()
		patch("connect.customer.doctype.starter_pack_order.implementation.frappe.enqueue").start()
		make_consultant(ONE, "Test Consultant-One")
		make_consultant(TWO, "Test Consultant-Two")

	def tearDown(self):
		patch.stopall()
		frappe.flags[PAYMENT_HOOK_FLAG] = False
		frappe.set_user("Administrator")

	def buyer(self, key):
		"""A signed-in buyer on their own customer company."""
		user = make_user(f"_test_consultant_buyer_{key}@example.com")
		company = f"_Test Consultant Buyer {key}"
		customer = frappe.db.get_value("Customer", {"customer_name": company}) or (
			frappe.get_doc({"doctype": "Customer", "customer_name": company}).insert(ignore_permissions=True).name
		)
		if not frappe.db.exists("Customer Team Member", {"user": user}):
			frappe.get_doc(
				{"doctype": "Customer Team Member", "customer": customer, "user": user, "is_admin": 1}
			).insert(ignore_permissions=True)
		return user, customer

	def paid_order(self, buyer=None):
		order = make_order([self.pack])
		frappe.flags[PAYMENT_HOOK_FLAG] = True
		order.payment_status = "Paid"
		order.save(ignore_permissions=True)
		frappe.flags[PAYMENT_HOOK_FLAG] = False
		if buyer:
			order.db_set({"user": buyer[0], "customer": buyer[1]})
		return order

	def handed_over(self, buyer=None):
		order = self.paid_order(buyer)
		hand_over(order.name)
		order.reload()
		return order

	# ---- The role ----

	def test_the_role_makes_a_consultant_on_the_frappe_team(self):
		consultant = frappe.get_doc("Frappe Consultant", ONE)
		self.assertEqual((consultant.full_name, consultant.enabled), ("Test Consultant-One", 1))
		self.assertTrue(
			frappe.db.exists(
				"Connect Partner Member", {"partner": FRAPPE, "user": ONE, "is_admin": 0, "is_removed": 0}
			)
		)
		self.assertIn(PARTNER_ROLE, frappe.get_roles(ONE))
		self.assertFalse(frappe.db.exists("Partner", {"partner_name": ["like", "%Consultant-One%"]}))

	def test_messaging_sees_a_consultant_as_frappes_side(self):
		frappe.set_user(ONE)
		context = get_my_context()
		self.assertEqual((context["partner"].partner, context["partner"].is_admin), (FRAPPE, 0))
		self.assertIsNone(context["customer"])

	def test_ticking_the_role_queues_the_set_up(self):
		user = make_user("_test_consultant_new@example.com")
		with patch("connect.partner.consultants.frappe.enqueue") as enqueue:
			doc = frappe.get_doc("User", user)
			doc.append("roles", {"role": CONSULTANT_ROLE})
			on_user_update(doc)
		enqueue.assert_called_once_with(sync_consultant, user=user, enqueue_after_commit=True)

	def test_saving_a_consultant_again_queues_nothing(self):
		with patch("connect.partner.consultants.frappe.enqueue") as enqueue:
			on_user_update(frappe.get_doc("User", ONE))
		enqueue.assert_not_called()

	def test_giving_the_role_back_switches_them_on_again(self):
		take_role_away(ONE)
		self.assertFalse(frappe.db.get_value("Frappe Consultant", ONE, "enabled"))
		make_consultant(ONE, "Test Consultant-One")
		self.assertTrue(frappe.db.get_value("Frappe Consultant", ONE, "enabled"))
		self.assertFalse(frappe.db.get_value("Connect Partner Member", {"partner": FRAPPE, "user": ONE}, "is_removed"))
		self.assertIn(PARTNER_ROLE, frappe.get_roles(ONE))

	# ---- Assignment ----

	def test_frappe_gets_the_order_and_consultants_take_turns(self):
		orders = [self.handed_over(self.buyer(key)) for key in ("a", "b", "c")]
		self.assertEqual([o.partner for o in orders], [FRAPPE] * 3)
		self.assertEqual([o.consultant for o in orders], [ONE, TWO, ONE])
		self.assertTrue(all(o.consultant_assigned_on for o in orders))

	def test_a_returning_customer_keeps_their_consultant(self):
		buyer = self.buyer("r")
		first = self.handed_over(buyer).consultant
		pointer = frappe.db.get_single_value(SETTINGS, "rr_last_consultant")
		self.assertEqual(self.handed_over(buyer).consultant, first)
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "rr_last_consultant"), pointer)

	def test_a_consultant_is_only_for_frappes_orders_and_must_be_enabled(self):
		order = self.handed_over(self.buyer("v"))
		take_role_away(TWO)
		order.consultant = TWO
		self.assertRaises(frappe.ValidationError, order.save, ignore_permissions=True)

	# ---- The chat ----

	def test_the_chat_is_with_the_consultant(self):
		buyer = self.buyer("t")
		order = self.handed_over(buyer)
		post_opening_message(order.name)
		thread = frappe.get_doc("Connect Thread", frappe.db.get_value("Starter Pack Order", order.name, "implementation_thread"))
		self.assertEqual((thread.partner, thread.consultant), (FRAPPE, order.consultant))
		self.assertEqual(thread_members(thread.name), {buyer[0], order.consultant})  # not Frappe's admin

		frappe.set_user(buyer[0])
		row = next(t for t in get_my_threads() if t["name"] == thread.name)
		self.assertEqual(row["consultant_name"], frappe.db.get_value("Frappe Consultant", order.consultant, "full_name"))

	def test_each_consultant_has_their_own_thread_with_a_customer(self):
		buyer = self.buyer("m")
		first = self.handed_over(buyer)
		post_opening_message(first.name)
		second = self.handed_over(buyer)
		second.consultant = TWO if first.consultant == ONE else ONE
		second.save(ignore_permissions=True)
		post_opening_message(second.name)
		threads = frappe.get_all("Connect Thread", filters={"customer": buyer[1], "partner": FRAPPE}, pluck="consultant")
		self.assertEqual(sorted(threads), sorted([ONE, TWO]))

	def test_contact_partner_keeps_its_own_thread(self):
		buyer = self.buyer("k")
		order = self.handed_over(buyer)
		post_opening_message(order.name)
		frappe.set_user(buyer[0])
		with patch("connect.api.contact.send_message"):
			contact = start_partner_thread(FRAPPE)
		contact = contact.get("thread") if isinstance(contact, dict) else contact
		self.assertNotEqual(contact, frappe.db.get_value("Starter Pack Order", order.name, "implementation_thread"))
		self.assertIsNone(frappe.db.get_value("Connect Thread", contact, "consultant"))

	def test_the_buyer_sees_their_consultant_on_the_setup_page_and_home(self):
		buyer = self.buyer("h")
		order = self.handed_over(buyer)
		full_name = frappe.db.get_value("Frappe Consultant", order.consultant, "full_name")
		self.assertEqual(get_order(order.name)["consultant"]["label"], full_name)
		frappe.set_user(buyer[0])
		project = next(p for p in get_my_projects() if p["order"] == order.name)
		self.assertEqual(project["partner"]["partner_name"], full_name)

	# ---- Nobody enabled ----

	def test_with_no_consultant_frappes_admin_has_the_chat_until_one_is_back(self):
		take_role_away(ONE)
		take_role_away(TWO)
		self.notify.reset_mock()
		buyer = self.buyer("n")
		order = self.handed_over(buyer)
		self.assertEqual((order.partner, order.consultant), (FRAPPE, None))
		self.notify.assert_called_once()  # admins are told
		post_opening_message(order.name)
		thread = frappe.db.get_value("Starter Pack Order", order.name, "implementation_thread")
		self.assertIn(FRAPPE_ADMIN, thread_members(thread))

		make_consultant(ONE, "Test Consultant-One")
		with patch("frappe.db.commit"):  # the job commits per order; not in a test
			hand_over_waiting_orders()
		self.assertEqual(frappe.db.get_value("Starter Pack Order", order.name, "consultant"), ONE)
		self.assertIn(ONE, thread_members(thread))

	# ---- A consultant stopping ----

	def test_stopping_hands_open_orders_and_their_threads_on(self):
		buyer = self.buyer("s")
		frappe.db.set_single_value(SETTINGS, {"rr_last_consultant": TWO, "rr_last_consultant_sequence": 99})
		order = self.handed_over(buyer)
		self.assertEqual(order.consultant, ONE)
		post_opening_message(order.name)
		thread = frappe.db.get_value("Starter Pack Order", order.name, "implementation_thread")

		take_role_away(ONE)

		order.reload()
		self.assertEqual((order.consultant, order.implementation_thread), (TWO, thread))
		self.assertEqual(frappe.db.get_value("Connect Thread", thread, "consultant"), TWO)
		self.assertEqual(thread_members(thread), {buyer[0], TWO})
		self.assertTrue(
			frappe.db.exists(
				"Connect Message", {"thread": thread, "message_type": "System", "content": ["like", "%Consultant-Two%"]}
			)
		)
		self.assertNotIn(PARTNER_ROLE, frappe.get_roles(ONE))
		frappe.set_user(ONE)
		self.assertIsNone(get_my_context()["partner"])

	def test_stopping_leaves_finished_orders_alone(self):
		order = self.handed_over(self.buyer("f"))
		order.db_set("status", "Completed")
		consultant = order.consultant
		take_role_away(consultant)
		self.assertEqual(frappe.db.get_value("Starter Pack Order", order.name, "consultant"), consultant)

	def test_a_new_partner_gets_their_own_thread_and_the_old_one_is_left_alone(self):
		buyer = self.buyer("p")
		order = self.handed_over(buyer)
		post_opening_message(order.name)
		old = frappe.db.get_value("Starter Pack Order", order.name, "implementation_thread")
		other = "_Test Other Starter Pack Partner"
		if not frappe.db.exists("Partner", other):
			frappe.get_doc(
				{"doctype": "Partner", "partner_name": other, "tier": "Gold", "country": "India", "starter_pack": 1}
			).insert(ignore_permissions=True)

		order.reload()
		order.update({"partner": other, "consultant": None})
		order.save(ignore_permissions=True)

		moved = frappe.db.get_value("Starter Pack Order", order.name, "implementation_thread")
		self.assertNotEqual(moved, old)
		self.assertEqual(frappe.db.get_value("Connect Thread", moved, ["partner", "consultant"]), (other, None))
		self.assertEqual(frappe.db.get_value("Connect Thread", old, "partner"), FRAPPE)
