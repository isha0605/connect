# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from connect.customer.doctype.starter_pack_order.starter_pack_order import PAYMENT_HOOK_FLAG

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = ["Customer", "Partner", "User"]


class IntegrationTestStarterPackOrder(IntegrationTestCase):
	"""The order is where money is decided, so these pin the pricing rules down."""

	def setUp(self):
		# Own packs, not the seeded catalog: a fresh test site has no seed, and
		# these must not depend on whatever prices ops has set.
		self.pack_a = make_pack("_test_pack_a", 10000, 5)
		self.pack_b = make_pack("_test_pack_b", 20000, 8)
		frappe.db.set_single_value("Starter Pack Settings", "gst_rate", 18)

	def tearDown(self):
		frappe.flags[PAYMENT_HOOK_FLAG] = False

	def test_prices_come_from_the_catalog_not_the_request(self):
		order = make_order([self.pack_a], sent_price=1)
		self.assertEqual(order.packs[0].price, 10000)

	def test_totals_add_gst_on_top(self):
		order = make_order([self.pack_a, self.pack_b])
		self.assertEqual(order.subtotal, 30000)
		self.assertEqual(order.gst_amount, 5400)
		self.assertEqual(order.amount, 35400)
		self.assertEqual(order.total_hours, 13)

	def test_rejects_the_same_pack_twice(self):
		self.assertRaises(frappe.ValidationError, make_order, [self.pack_a, self.pack_a])

	def test_rejects_an_inactive_pack(self):
		frappe.db.set_value("Starter Pack", self.pack_a, "is_active", 0)
		self.assertRaises(frappe.ValidationError, make_order, [self.pack_a])

	def test_packs_are_frozen_once_placed(self):
		order = make_order([self.pack_a])
		order.append("packs", {"starter_pack": self.pack_b})
		self.assertRaises(frappe.ValidationError, order.save, ignore_permissions=True)

	def test_a_catalog_price_change_never_reprices_an_order(self):
		order = make_order([self.pack_a])
		frappe.db.set_value("Starter Pack", self.pack_a, "price", 99999)
		order.reload()
		order.status = "In Progress"
		order.save(ignore_permissions=True)
		self.assertEqual(order.packs[0].price, 10000)
		self.assertEqual(order.amount, 11800)

	def test_payment_status_cannot_be_set_by_hand(self):
		order = make_order([self.pack_a])
		order.payment_status = "Paid"
		self.assertRaises(frappe.ValidationError, order.save, ignore_permissions=True)

	def test_payment_hook_can_set_payment_status(self):
		order = make_order([self.pack_a])
		frappe.flags[PAYMENT_HOOK_FLAG] = True
		order.payment_status = "Paid"
		order.save(ignore_permissions=True)
		self.assertEqual(order.payment_status, "Paid")

	def test_no_refund_after_kickoff(self):
		order = make_order([self.pack_a])
		frappe.flags[PAYMENT_HOOK_FLAG] = True
		order.payment_status = "Paid"
		order.kickoff_date = today()
		order.save(ignore_permissions=True)
		order.payment_status = "Refunded"
		self.assertRaises(frappe.ValidationError, order.save, ignore_permissions=True)


def make_pack(pack_key, price, total_hours):
	if not frappe.db.exists("Starter Pack", pack_key):
		frappe.get_doc(
			{
				"doctype": "Starter Pack",
				"pack_key": pack_key,
				"pack_name": pack_key,
				"price": price,
				"total_hours": total_hours,
				"delivery_days": 30,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
	else:
		frappe.db.set_value("Starter Pack", pack_key, {"price": price, "total_hours": total_hours, "is_active": 1})
	return pack_key


def make_order(packs, sent_price=None):
	return frappe.get_doc(
		{
			"doctype": "Starter Pack Order",
			"company_name": "Test Co",
			"terms_accepted": 1,
			"packs": [{"starter_pack": p, "price": sent_price} for p in packs],
		}
	).insert(ignore_permissions=True)
