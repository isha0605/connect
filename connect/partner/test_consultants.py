# Copyright (c) 2026
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.api.contact import start_partner_thread
from connect.customer.doctype.shortlist.shortlist import add_to_shortlist
from connect.customer.doctype.starter_pack_order.implementation import hand_over, post_opening_message
from connect.customer.doctype.starter_pack_order.starter_pack_order import PAYMENT_HOOK_FLAG
from connect.customer.doctype.starter_pack_order.test_starter_pack_order import make_order, make_pack, make_user
from connect.partner.consultants import get_consultant_partner, on_user_update, sync_consultant
from connect.partner.doctype.partner.partner import (
	get_partner_document,
	get_partner_preview,
	list_partner_countries,
	list_partners_by_names,
)
from connect.roles import CONSULTANT_ROLE, PARTNER_ROLE
from connect.utils import get_my_context

NOTIFY = "frappe.desk.doctype.notification_log.notification_log.enqueue_create_notification"
SETTINGS = "Starter Pack Settings"



def make_consultant(email, full_name):
	"""A User with the Frappe Consultant role, set up as the role's hook would set them up."""
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": full_name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	frappe.get_doc("User", email).add_roles(CONSULTANT_ROLE)
	sync_consultant(email)
	return get_consultant_partner(email)


def take_role_away(email):
	frappe.get_doc("User", email).remove_roles(CONSULTANT_ROLE)
	sync_consultant(email)


class IntegrationTestFrappeConsultants(IntegrationTestCase):
	def setUp(self):
		# Only this class's consultants take part; the rollback puts the site's back.
		for name in frappe.get_all("Partner", filters={"starter_pack": 1}, pluck="name"):
			frappe.db.set_value("Partner", name, {"starter_pack": 0, "starter_pack_sequence": 0})
		self.frappe_partner = "_Test Frappe"
		if not frappe.db.exists("Partner", self.frappe_partner):
			frappe.get_doc(
				{"doctype": "Partner", "partner_name": self.frappe_partner, "tier": "Gold", "country": "India"}
			).insert(ignore_permissions=True)
		frappe.db.set_single_value(
			SETTINGS,
			{
				"implementation_partner": self.frappe_partner,
				"auto_assign_partners": 1,
				"rr_last_partner": "",
				"rr_last_sequence": 0,
				"gst_rate": 18,
			},
		)
		self.pack = make_pack("_test_pack_a", 10000, 5)
		self.notify = patch(NOTIFY).start()
		patch("frappe.log_error").start()
		self.enqueue = patch("connect.customer.doctype.starter_pack_order.implementation.frappe.enqueue").start()
		self.one = make_consultant("_test_consultant_one@example.com", "Test Consultant One")
		self.two = make_consultant("_test_consultant_two@example.com", "Test Consultant Two")
		frappe.db.set_value("Partner", [self.one, self.two], "is_featured", 0)  # records outlive a test

	def tearDown(self):
		patch.stopall()
		frappe.flags[PAYMENT_HOOK_FLAG] = False
		frappe.set_user("Administrator")

	def paid_order(self, customer=None):
		order = make_order([self.pack])
		frappe.flags[PAYMENT_HOOK_FLAG] = True
		order.payment_status = "Paid"
		order.save(ignore_permissions=True)
		frappe.flags[PAYMENT_HOOK_FLAG] = False
		if customer:
			order.db_set("customer", customer)
		return order

	def make_buyer(self, email, company):
		user = make_user(email)
		customer = frappe.db.get_value("Customer", {"customer_name": company}) or (
			frappe.get_doc({"doctype": "Customer", "customer_name": company}).insert(ignore_permissions=True).name
		)
		if not frappe.db.exists("Customer Team Member", {"user": user}):
			frappe.get_doc(
				{"doctype": "Customer Team Member", "customer": customer, "user": user, "is_admin": 1}
			).insert(ignore_permissions=True)
		return user, customer

	# ---- The role ----

	def test_the_role_makes_a_consultant_partner_with_the_user_as_admin(self):
		partner = frappe.get_doc("Partner", self.one)
		self.assertEqual(partner.partner_name, "Test Consultant One · Frappe")
		self.assertEqual(
			(partner.is_frappe_consultant, partner.starter_pack, partner.enabled, partner.is_featured), (1, 1, 1, 0)
		)
		self.assertTrue(
			frappe.db.exists(
				"Connect Partner Member",
				{"partner": self.one, "user": "_test_consultant_one@example.com", "is_admin": 1},
			)
		)
		self.assertIn(PARTNER_ROLE, frappe.get_roles("_test_consultant_one@example.com"))

	def test_messaging_sees_a_consultant_as_the_partner_side(self):
		frappe.set_user("_test_consultant_one@example.com")
		context = get_my_context()
		self.assertEqual((context["partner"].partner, context["partner"].is_admin), (self.one, 1))
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
			on_user_update(frappe.get_doc("User", "_test_consultant_one@example.com"))
		enqueue.assert_not_called()

	def test_giving_the_role_back_switches_them_on_again(self):
		take_role_away("_test_consultant_one@example.com")
		self.assertFalse(frappe.db.get_value("Partner", self.one, "enabled"))
		self.assertEqual(make_consultant("_test_consultant_one@example.com", "Test Consultant One"), self.one)
		self.assertTrue(frappe.db.get_value("Partner", self.one, "enabled"))
		self.assertIn(PARTNER_ROLE, frappe.get_roles("_test_consultant_one@example.com"))

	# ---- Never listed ----

	def test_never_listed_even_when_featured(self):
		frappe.db.set_value("Partner", self.one, {"is_featured": 1, "country": "_Testland"})
		self.assertEqual(list_partners_by_names([self.one]), [])
		self.assertNotIn("_Testland", list_partner_countries())

	def test_a_buyer_cannot_open_find_save_or_contact_a_consultant(self):
		user, _customer = self.make_buyer("_test_consultant_buyer@example.com", "_Test Consultant Buyer Co")
		frappe.set_user(user)
		self.assertRaises(frappe.DoesNotExistError, get_partner_document, self.one)
		self.assertRaises(frappe.DoesNotExistError, get_partner_preview, self.one)
		self.assertRaises(frappe.DoesNotExistError, add_to_shortlist, self.one)
		self.assertRaises(frappe.DoesNotExistError, start_partner_thread, self.one)

	def test_the_consultant_can_still_open_their_own_profile(self):
		frappe.set_user("_test_consultant_one@example.com")
		self.assertEqual(get_partner_document(self.one)["name"], self.one)

	# ---- Assignment ----

	def test_orders_alternate_between_consultants(self):
		_u, a = self.make_buyer("_test_consultant_buyer_a@example.com", "_Test Buyer A")
		_u, b = self.make_buyer("_test_consultant_buyer_b@example.com", "_Test Buyer B")
		_u, c = self.make_buyer("_test_consultant_buyer_c@example.com", "_Test Buyer C")
		picks = [hand_over(self.paid_order(customer).name) for customer in (a, b, c)]
		self.assertEqual(picks, [self.one, self.two, self.one])

	def test_outside_partners_are_left_out_of_the_pool(self):
		frappe.db.set_value("Partner", self.frappe_partner, "starter_pack", 1)
		frappe.db.set_value("Partner", [self.one, self.two], "enabled", 0)
		self.assertEqual(hand_over(self.paid_order().name), self.frappe_partner)  # the fallback, not the pool

	def test_a_returning_customer_keeps_their_consultant(self):
		_u, customer = self.make_buyer("_test_consultant_buyer_r@example.com", "_Test Returning Buyer")
		first = hand_over(self.paid_order(customer).name)
		pointer = frappe.db.get_single_value(SETTINGS, "rr_last_partner")
		self.assertEqual(hand_over(self.paid_order(customer).name), first)
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "rr_last_partner"), pointer)

	def test_with_no_consultant_the_order_goes_to_implemented_by_and_admins_are_told(self):
		frappe.db.set_value("Partner", [self.one, self.two], "enabled", 0)
		self.assertEqual(hand_over(self.paid_order().name), self.frappe_partner)
		self.notify.assert_called_once()

	# ---- A consultant stopping ----

	def test_stopping_hands_open_orders_and_their_threads_to_the_other_consultant(self):
		user, customer = self.make_buyer("_test_consultant_buyer_s@example.com", "_Test Stopping Buyer")
		order = self.paid_order(customer)
		order.db_set("user", user)
		self.assertEqual(hand_over(order.name), self.one)
		post_opening_message(order.name)
		thread = frappe.db.get_value("Starter Pack Order", order.name, "implementation_thread")
		self.assertTrue(thread)

		take_role_away("_test_consultant_one@example.com")

		order.reload()
		self.assertEqual((order.partner, order.implementation_thread), (self.two, thread))
		member = {"thread": thread, "side": "Partner", "is_removed": 0}
		self.assertTrue(frappe.db.exists("Connect Thread Member", {**member, "user": "_test_consultant_two@example.com"}))
		self.assertFalse(frappe.db.exists("Connect Thread Member", {**member, "user": "_test_consultant_one@example.com"}))
		self.assertTrue(
			frappe.db.exists(
				"Connect Message",
				{"thread": thread, "message_type": "System", "content": ["like", "%Test Consultant Two%"]},
			)
		)
		self.assertNotIn(PARTNER_ROLE, frappe.get_roles("_test_consultant_one@example.com"))
		self.assertFalse(frappe.db.get_value("Partner", self.one, "enabled"))

	def test_stopping_leaves_finished_orders_alone(self):
		_u, customer = self.make_buyer("_test_consultant_buyer_f@example.com", "_Test Finished Buyer")
		order = self.paid_order(customer)
		hand_over(order.name)
		order.db_set("status", "Completed")
		take_role_away("_test_consultant_one@example.com")
		self.assertEqual(frappe.db.get_value("Starter Pack Order", order.name, "partner"), self.one)
