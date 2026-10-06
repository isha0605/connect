# Copyright (c) 2026, Isha and Contributors
# See license.txt

from datetime import datetime
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from connect.customer.doctype.starter_pack_order.starter_pack_order import (
	PAYMENT_HOOK_FLAG,
	checkout,
	get_my_projects,
	get_order,
	pay,
)

RAZORPAY = "bwh_payments.bwh_payments.doctype.razorpay_gateway_settings.razorpay_gateway_settings.RazorpayGatewaySettings"
ORDER_MODULE = "connect.customer.doctype.starter_pack_order.starter_pack_order"
GPR_MODULE = "bwh_payments.bwh_payments.doctype.gateway_payment_request.gateway_payment_request"
from connect.customer.doctype.starter_pack_order.implementation import (
	hand_over,
	hand_over_waiting_orders,
	post_opening_message,
)
from connect.customer.doctype.starter_pack_order.partner_rotation import (
	assign_partner,
	pick_next,
	read_pointer,
)

NOTIFY = "frappe.desk.doctype.notification_log.notification_log.enqueue_create_notification"
IMPLEMENTATION_MODULE = "connect.customer.doctype.starter_pack_order.implementation"
ROTATION_MODULE = "connect.customer.doctype.starter_pack_order.partner_rotation"

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


class IntegrationTestStarterPackOrderPartner(IntegrationTestCase):
	"""Frappe assigns the partner, and only from its approved Starter Pack pool."""

	def setUp(self):
		self.pack = make_pack("_test_pack_a", 10000, 5)
		frappe.db.set_single_value("Starter Pack Settings", "gst_rate", 18)
		self.approved = make_partner("_Test Starter Pack Partner", starter_pack=1)
		self.unapproved = make_partner("_Test Other Partner", starter_pack=0)

	def tearDown(self):
		frappe.flags[PAYMENT_HOOK_FLAG] = False

	def paid_order(self):
		order = make_order([self.pack])
		frappe.flags[PAYMENT_HOOK_FLAG] = True
		order.payment_status = "Paid"
		order.save(ignore_permissions=True)
		frappe.flags[PAYMENT_HOOK_FLAG] = False
		return order

	def test_no_partner_before_payment(self):
		order = make_order([self.pack])
		order.partner = self.approved
		self.assertRaises(frappe.ValidationError, order.save, ignore_permissions=True)

	def test_rejects_a_partner_outside_the_pool(self):
		order = self.paid_order()
		order.partner = self.unapproved
		self.assertRaises(frappe.ValidationError, order.save, ignore_permissions=True)

	def test_assigns_an_approved_partner_once_paid(self):
		order = self.paid_order()
		order.partner = self.approved
		order.save(ignore_permissions=True)
		self.assertEqual(order.partner, self.approved)


class IntegrationTestStarterPackPayment(IntegrationTestCase):
	"""Checkout and the gateway round trip, against a mocked Razorpay: no network,
	and no keys needed. The bwh_payments code itself runs for real."""

	def setUp(self):
		self.pack_a = make_pack("_test_pack_a", 10000, 5)
		self.pack_b = make_pack("_test_pack_b", 20000, 8)
		frappe.db.set_single_value("Starter Pack Settings", "gst_rate", 18)
		frappe.db.set_single_value("Starter Pack Settings", "currency", "INR")
		if not frappe.db.exists("Payment Gateway Profile", "_Test Razorpay"):
			frappe.get_doc(
				{
					"doctype": "Payment Gateway Profile",
					"__newname": "_Test Razorpay",
					"gateway_settings": "Razorpay Gateway Settings",
					"enabled": 1,
				}
			).insert(ignore_permissions=True)
		frappe.db.set_single_value("Starter Pack Settings", "payment_gateway", "_Test Razorpay")
		frappe.db.set_single_value(
			"Starter Pack Settings", {"implementation_partner": "", "auto_assign_partners": 0}
		)

		# Records persist across tests within a class (the rollback is per class), and
		# order_ref is unique, so every fake session needs its own id.
		self.patches = [
			patch(
				f"{RAZORPAY}.create_session",
				side_effect=lambda *a, **k: {
					"session_id": f"plink_test_{frappe.generate_hash(length=12)}",
					"redirect_url": "https://rzp.io/test",
				},
			),
			patch(f"{RAZORPAY}.get_payment_status", return_value="Pending"),
			patch(f"{ORDER_MODULE}.get_captured_payment_id", return_value="pay_test_1"),
			# refund() logs through frappe's create_request_log, which commits. In a test
			# that would persist everything the class created, so the log is stubbed.
			patch(f"{GPR_MODULE}.create_request_log", return_value=MagicMock()),
			patch("frappe.log_error"),
		]
		for p in self.patches:
			p.start()

	def tearDown(self):
		for p in self.patches:
			p.stop()
		frappe.flags[PAYMENT_HOOK_FLAG] = False

	def place(self, packs):
		result = checkout(
			frappe.as_json(packs),
			"Test Co",
			phone="9999999999",
			terms_accepted=1,
			buyer_name="Asha Rao",
			buyer_email="asha@example.com",
		)
		return result, frappe.get_doc("Starter Pack Order", result["order"])

	def request(self, order):
		return frappe.get_doc("Gateway Payment Request", order.payment_request)

	def test_checkout_charges_the_server_price(self):
		result, order = self.place([self.pack_a, self.pack_b])
		self.assertEqual(result["amount"], 35400)
		self.assertEqual(result["payment_url"], "https://rzp.io/test")
		request = self.request(order)
		self.assertEqual(request.amount, 35400)
		self.assertEqual(request.currency_code, "INR")
		self.assertEqual((request.ref_doctype, request.ref_docname), ("Starter Pack Order", order.name))

	def test_checkout_needs_terms_a_pack_and_a_buyer(self):
		buyer = {"buyer_name": "Asha Rao", "buyer_email": "asha@example.com"}
		self.assertRaises(frappe.ValidationError, checkout, frappe.as_json([self.pack_a]), "Test Co", **buyer)
		self.assertRaises(frappe.ValidationError, checkout, "[]", "Test Co", terms_accepted=1, **buyer)
		packs = frappe.as_json([self.pack_a])
		self.assertRaises(frappe.ValidationError, checkout, packs, "Test Co", terms_accepted=1, buyer_email="a@b.co")
		self.assertRaises(frappe.ValidationError, checkout, packs, "Test Co", terms_accepted=1, buyer_name="Asha")
		self.assertRaises(
			frappe.ValidationError, checkout, packs, "Test Co", terms_accepted=1, buyer_name="Asha", buyer_email="nope"
		)

	def test_a_guest_can_buy_without_an_account(self):
		users_before = frappe.db.count("User")
		frappe.set_user("Guest")
		try:
			result, order = self.place([self.pack_a])
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("User"), users_before)
		self.assertEqual((order.user, order.customer), ("Guest", None))
		self.assertEqual((order.buyer_name, order.buyer_email, order.company_name), ("Asha Rao", "asha@example.com", "Test Co"))
		self.assertEqual(result["key"], order.access_key)
		# What was typed at checkout is what the payment request, and so Razorpay, gets.
		request = self.request(order)
		self.assertEqual(
			(request.customer_forenames, request.customer_surname, request.customer_email, request.customer_phone),
			("Asha", "Rao", "asha@example.com", "9999999999"),
		)

	def test_a_guest_reads_their_order_back_only_with_its_key(self):
		frappe.set_user("Guest")
		try:
			result, order = self.place([self.pack_a])
			self.assertEqual(get_order(payment_request=result["payment_request"], key=result["key"])["order"], order.name)
			self.assertRaises(frappe.PermissionError, get_order, order.name)
			self.assertRaises(frappe.PermissionError, get_order, order.name, key="not-the-key")
			self.assertEqual(pay(order.name, key=result["key"])["order"], order.name)
			self.assertRaises(frappe.PermissionError, pay, order.name)
		finally:
			frappe.set_user("Administrator")

	def test_webhook_marks_the_order_paid(self):
		_, order = self.place([self.pack_a])
		self.request(order).apply_webhook_status("Paid", "evt_1")
		order.reload()
		self.assertEqual(order.payment_status, "Paid")
		self.assertEqual(order.gateway_payment_id, "pay_test_1")
		self.assertTrue(order.paid_on)

	def test_payment_gives_the_order_to_the_implementation_partner(self):
		make_partner("_Test Implementing Partner", starter_pack=0)
		frappe.db.set_single_value("Starter Pack Settings", "implementation_partner", "_Test Implementing Partner")

		_, order = self.place([self.pack_a])
		with patch(f"{IMPLEMENTATION_MODULE}.frappe.enqueue") as enqueue:
			self.request(order).apply_webhook_status("Paid", "evt_1")
		order.reload()
		self.assertEqual(order.partner, "_Test Implementing Partner")
		self.assertFalse(order.partner_auto_assigned)
		self.assertEqual(order.status, "Partner Assigned")
		enqueue.assert_called_once_with(post_opening_message, order_name=order.name, enqueue_after_commit=True)

	def test_payment_assigns_a_partner_by_round_robin_when_switched_on(self):
		frappe.db.set_single_value("Starter Pack Settings", "auto_assign_partners", 1)
		make_partner("_Test RR Payment Partner", starter_pack=0)
		partner = frappe.get_doc("Partner", "_Test RR Payment Partner")
		partner.update({"starter_pack": 1, "enabled": 1, "is_frappe_consultant": 1, "starter_pack_sequence": 0})
		partner.save(ignore_permissions=True)

		_, order = self.place([self.pack_a])
		self.request(order).apply_webhook_status("Paid", "evt_1")
		order.reload()
		self.assertTrue(order.partner)
		self.assertTrue(order.partner_auto_assigned)
		self.assertEqual(order.status, "Partner Assigned")

	def test_a_replayed_webhook_changes_nothing(self):
		_, order = self.place([self.pack_a])
		self.assertTrue(self.request(order).apply_webhook_status("Paid", "evt_1"))
		self.assertFalse(self.request(order).apply_webhook_status("Paid", "evt_1"))
		order.reload()
		self.assertEqual(order.payment_status, "Paid")

	def test_an_expired_link_fails_the_order(self):
		_, order = self.place([self.pack_a])
		self.request(order).apply_webhook_status("Expired", "evt_1")
		order.reload()
		self.assertEqual(order.payment_status, "Failed")

	def test_paying_again_reuses_an_open_link(self):
		_, order = self.place([self.pack_a])
		self.assertEqual(order.create_payment_request().name, order.payment_request)

	def test_a_dead_link_can_be_retried(self):
		_, order = self.place([self.pack_a])
		first = order.payment_request
		self.request(order).apply_webhook_status("Expired", "evt_1")
		order.reload()
		self.assertEqual(order.payment_status, "Failed")

		retry = pay(order.name)
		order.reload()
		self.assertNotEqual(order.payment_request, first)
		self.assertEqual(order.payment_status, "Unpaid")
		self.assertEqual(retry["payment_url"], "https://rzp.io/test")

		self.request(order).apply_webhook_status("Paid", "evt_2")
		order.reload()
		self.assertEqual(order.payment_status, "Paid")

	def test_the_return_page_finds_the_order_by_its_payment_request(self):
		_, order = self.place([self.pack_a, self.pack_b])
		self.request(order).apply_webhook_status("Paid", "evt_1")
		result = get_order(payment_request=order.payment_request)
		self.assertEqual(result["order"], order.name)
		self.assertEqual(result["payment_status"], "Paid")
		self.assertEqual((result["subtotal"], result["gst_amount"], result["amount"]), (30000, 5400, 35400))
		self.assertEqual([p["total_hours"] for p in result["packs"]], [5, 8])

	def test_the_confirmed_page_gets_the_partner_and_when_things_happened(self):
		frappe.db.set_single_value("Starter Pack Settings", "auto_assign_partners", 1)
		make_partner("_Test RR Payment Partner", starter_pack=0)
		partner = frappe.get_doc("Partner", "_Test RR Payment Partner")
		partner.update({"starter_pack": 1, "enabled": 1, "is_frappe_consultant": 1, "starter_pack_sequence": 0})
		partner.save(ignore_permissions=True)

		_, order = self.place([self.pack_a])
		self.request(order).apply_webhook_status("Paid", "evt_1")
		result = get_order(order.name)

		order.reload()
		self.assertEqual(result["partner"]["name"], order.partner)
		self.assertIsInstance(result["partner"]["industries"], list)
		self.assertEqual(result["partner"]["review_count"], frappe.db.count("Partner Review", {"partner": order.partner}))
		# Sent with the site's offset, so a browser in another zone reads the right moment.
		for field in ("created_on", "paid_on", "partner_assigned_on"):
			self.assertIsNotNone(datetime.fromisoformat(result[field]).utcoffset(), field)

	def test_the_return_page_is_only_for_the_buyer(self):
		_, order = self.place([self.pack_a])
		frappe.set_user("Guest")
		try:
			self.assertRaises(frappe.PermissionError, get_order, payment_request=order.payment_request)
		finally:
			frappe.set_user("Administrator")

	def test_a_paid_order_cannot_be_paid_again(self):
		_, order = self.place([self.pack_a])
		self.request(order).apply_webhook_status("Paid", "evt_1")
		self.assertRaises(frappe.ValidationError, pay, order.name)

	def test_a_superseded_link_being_paid_leaves_the_order_alone(self):
		_, order = self.place([self.pack_a])
		old = self.request(order)
		order.db_set("payment_request", None)
		new = order.create_payment_request()
		old.reload()
		old.apply_webhook_status("Paid", "evt_old")
		order.reload()
		self.assertEqual(order.payment_request, new.name)
		self.assertEqual(order.payment_status, "Unpaid")

	def test_refund_before_kickoff_goes_through(self):
		_, order = self.place([self.pack_a])
		self.request(order).apply_webhook_status("Paid", "evt_1")
		with patch(f"{RAZORPAY}.refund_payment", return_value={"refund_id": "rfnd_1"}) as refund:
			self.request(order).refund()
		refund.assert_called_once()
		order.reload()
		self.assertEqual(order.payment_status, "Refunded")

	def test_no_refund_after_kickoff_and_razorpay_is_never_called(self):
		_, order = self.place([self.pack_a])
		self.request(order).apply_webhook_status("Paid", "evt_1")
		order.reload()
		order.kickoff_date = today()
		order.save(ignore_permissions=True)
		with patch(f"{RAZORPAY}.refund_payment") as refund:
			self.assertRaises(frappe.ValidationError, self.request(order).refund)
		refund.assert_not_called()
		order.reload()
		self.assertEqual(order.payment_status, "Paid")


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


def make_partner(partner_name, starter_pack):
	if not frappe.db.exists("Partner", partner_name):
		tier = next(t for t in frappe.get_meta("Partner").get_field("tier").options.split("\n") if t)
		frappe.get_doc(
			{"doctype": "Partner", "partner_name": partner_name, "tier": tier, "country": "India"}
		).insert(ignore_permissions=True)
	frappe.db.set_value("Partner", partner_name, "starter_pack", starter_pack)
	return partner_name


def make_order(packs, sent_price=None):
	return frappe.get_doc(
		{
			"doctype": "Starter Pack Order",
			"company_name": "Test Co",
			"terms_accepted": 1,
			"packs": [{"starter_pack": p, "price": sent_price} for p in packs],
		}
	).insert(ignore_permissions=True)


def pool_of(*partners):
	"""(name, rotation order) pairs -> the rows get_pool returns, in its order."""
	from connect.customer.doctype.starter_pack_order.partner_rotation import rotation_key

	rows = [frappe._dict(name=name, starter_pack_sequence=seq) for name, seq in partners]
	return sorted(rows, key=lambda p: rotation_key(p.starter_pack_sequence, p.name))


class UnitTestPartnerRotation(IntegrationTestCase):
	"""Who comes next, for every shape of pool and pointer. No database involved."""

	ABCD = (("A", 1), ("B", 2), ("C", 3), ("D", 4))

	def next_after(self, pool, pointer):
		return pick_next(pool_of(*pool), pointer).name

	def test_first_ever_pick_is_the_lowest_rotation_order(self):
		self.assertEqual(self.next_after(self.ABCD, None), "A")

	def test_wraps_from_the_last_partner_to_the_first(self):
		self.assertEqual(self.next_after(self.ABCD, (4, "D")), "A")

	def test_a_new_partner_joins_the_cycle_in_order(self):
		pool = (*self.ABCD, ("E", 5))
		picks, pointer = [], (3, "C")
		for _ in range(3):
			partner = pick_next(pool_of(*pool), pointer)
			picks.append(partner.name)
			pointer = (partner.starter_pack_sequence, partner.name)
		self.assertEqual(picks, ["D", "E", "A"])

	def test_a_partner_going_inactive_mid_cycle_is_skipped(self):
		self.assertEqual(self.next_after((("A", 1), ("B", 2), ("D", 4)), (2, "B")), "D")

	def test_recovers_when_the_pointer_partner_is_gone(self):
		# Inactive, taken out of the pool or deleted all look the same from here:
		# the pointer's partner just isn't in the pool any more.
		without_c = (("A", 1), ("B", 2), ("D", 4))
		self.assertEqual(self.next_after(without_c, (3, "C")), "D")
		self.assertEqual(self.next_after((("A", 1), ("B", 2)), (3, "C")), "A")

	def test_a_single_partner_gets_every_order(self):
		self.assertEqual(self.next_after((("A", 1),), (1, "A")), "A")
		self.assertEqual(self.next_after((("A", 1),), None), "A")

	def test_a_duplicate_rotation_order_breaks_ties_by_name(self):
		# Saving a Partner rejects duplicates; this only guards a direct database edit.
		pool = (("A", 1), ("B", 1), ("C", 2))
		self.assertEqual(self.next_after(pool, (1, "A")), "B")
		self.assertEqual(self.next_after(pool, (1, "B")), "C")

	def test_a_partner_without_a_rotation_order_still_takes_part_last(self):
		pool = (("A", 1), ("B", 0), ("C", 2))
		self.assertEqual(self.next_after(pool, (2, "C")), "B")
		self.assertEqual(self.next_after(pool, (0, "B")), "A")

	def test_an_empty_pool_picks_nobody(self):
		self.assertIsNone(pick_next([], (1, "A")))


class IntegrationTestPartnerRotation(IntegrationTestCase):
	"""Paid orders handed out by the round robin, against a pool this class controls."""

	def setUp(self):
		# Take the site's real Starter Pack partners out of the pool for this class; the
		# class's rollback puts them back.
		for name in frappe.get_all("Partner", filters={"starter_pack": 1}, pluck="name"):
			frappe.db.set_value("Partner", name, {"starter_pack": 0, "starter_pack_sequence": 0})
		frappe.db.set_single_value("Starter Pack Settings", "rr_last_partner", "")
		frappe.db.set_single_value("Starter Pack Settings", "rr_last_sequence", 0)
		frappe.db.set_single_value("Starter Pack Settings", "auto_assign_partners", 1)
		frappe.db.set_single_value("Starter Pack Settings", "gst_rate", 18)
		self.pack = make_pack("_test_pack_a", 10000, 5)
		self.notify = patch(NOTIFY).start()
		self.log_error = patch("frappe.log_error").start()
		# Every order here is placed by one user, who'd otherwise go back to their first
		# consultant each time. That rule has its own tests (connect.partner.test_consultants).
		patch(f"{ROTATION_MODULE}.previous_partner", return_value=None).start()

	def tearDown(self):
		patch.stopall()
		frappe.flags[PAYMENT_HOOK_FLAG] = False

	def approve(self, name, sequence=0):
		if not frappe.db.exists("Partner", name):
			make_partner(name, starter_pack=0)
		doc = frappe.get_doc("Partner", name)
		doc.update({"starter_pack": 1, "enabled": 1, "is_frappe_consultant": 1, "starter_pack_sequence": sequence})
		doc.save(ignore_permissions=True)
		return doc

	def paid_order(self):
		order = make_order([self.pack])
		frappe.flags[PAYMENT_HOOK_FLAG] = True
		order.payment_status = "Paid"
		order.save(ignore_permissions=True)
		frappe.flags[PAYMENT_HOOK_FLAG] = False
		return order

	def test_approval_puts_a_partner_at_the_end_of_the_line(self):
		a = self.approve("_Test RR A")
		b = self.approve("_Test RR B")
		self.assertEqual(b.starter_pack_sequence, a.starter_pack_sequence + 1)

	def test_rotation_order_must_be_unique(self):
		self.approve("_Test RR A", 1)
		self.assertRaises(frappe.ValidationError, self.approve, "_Test RR B", 1)

	def test_leaving_the_pool_gives_up_the_place(self):
		a = self.approve("_Test RR A", 1)
		a.starter_pack = 0
		a.save(ignore_permissions=True)
		self.assertEqual(a.starter_pack_sequence, 0)

	def test_orders_go_round_the_pool(self):
		self.approve("_Test RR A", 1)
		self.approve("_Test RR B", 2)
		picks = [assign_partner(self.paid_order().name) for _ in range(3)]
		self.assertEqual(picks, ["_Test RR A", "_Test RR B", "_Test RR A"])

		order = frappe.get_last_doc("Starter Pack Order")
		self.assertEqual(order.status, "Partner Assigned")
		self.assertTrue(order.partner_auto_assigned)
		self.assertTrue(order.partner_assigned_on)
		self.assertEqual(read_pointer(), (1, "_Test RR A"))

	def test_assigning_by_hand_leaves_the_rotation_alone(self):
		self.approve("_Test RR A", 1)
		self.approve("_Test RR B", 2)
		self.assertEqual(assign_partner(self.paid_order().name), "_Test RR A")

		by_hand = self.paid_order()
		by_hand.partner = "_Test RR A"
		by_hand.save(ignore_permissions=True)
		self.assertFalse(by_hand.partner_auto_assigned)
		self.assertEqual(read_pointer(), (1, "_Test RR A"))

		self.assertEqual(assign_partner(self.paid_order().name), "_Test RR B")

	def test_an_assigned_order_is_not_reassigned(self):
		self.approve("_Test RR A", 1)
		self.approve("_Test RR B", 2)
		order = self.paid_order()
		self.assertEqual(assign_partner(order.name), "_Test RR A")
		self.assertEqual(assign_partner(order.name), "_Test RR A")  # e.g. a replayed webhook
		self.assertEqual(read_pointer(), (1, "_Test RR A"))

	def test_unpaid_orders_are_not_assigned(self):
		self.approve("_Test RR A", 1)
		self.assertIsNone(assign_partner(make_order([self.pack]).name))

	def test_no_partner_available_leaves_the_order_paid_and_tells_admins(self):
		order = self.paid_order()
		self.assertIsNone(assign_partner(order.name))
		order.reload()
		self.assertEqual((order.payment_status, order.status, order.partner), ("Paid", "New", None))
		self.notify.assert_called_once()
		self.assertTrue(
			frappe.db.exists("Comment", {"reference_name": order.name, "comment_type": "Info"})
		)

	def test_a_waiting_order_is_picked_up_once_a_partner_is_approved(self):
		order = self.paid_order()
		assign_partner(order.name)
		self.notify.reset_mock()

		self.approve("_Test RR A", 1)
		with patch("frappe.db.commit"):  # the job commits per order; not in a test
			hand_over_waiting_orders()
		order.reload()
		self.assertEqual(order.partner, "_Test RR A")
		self.notify.assert_not_called()  # admins were already told, at payment

	def test_a_failed_pointer_save_undoes_the_assignment(self):
		self.approve("_Test RR A", 1)
		order = self.paid_order()
		with patch(f"{ROTATION_MODULE}.write_pointer", side_effect=frappe.QueryTimeoutError):
			self.assertIsNone(assign_partner(order.name))
		order.reload()
		self.assertEqual((order.payment_status, order.partner), ("Paid", None))
		self.assertIsNone(read_pointer())
		self.log_error.assert_called()
		self.notify.assert_called_once()


class IntegrationTestStarterPackImplementation(IntegrationTestCase):
	"""With the round robin off, every paid order goes to the Implemented By partner, and a
	signed-in buyer's opening message to them is posted in their thread."""

	def setUp(self):
		for name in frappe.get_all("Partner", filters={"starter_pack": 1}, pluck="name"):
			frappe.db.set_value("Partner", name, {"starter_pack": 0, "starter_pack_sequence": 0})
		self.partner = make_partner("_Test Implementing Partner", starter_pack=0)
		frappe.db.set_single_value(
			"Starter Pack Settings",
			{"implementation_partner": self.partner, "auto_assign_partners": 0, "gst_rate": 18},
		)
		self.pack = make_pack("_test_pack_a", 10000, 5)
		self.notify = patch(NOTIFY).start()
		self.log_error = patch("frappe.log_error").start()
		self.enqueue = patch(f"{IMPLEMENTATION_MODULE}.frappe.enqueue").start()

	def tearDown(self):
		patch.stopall()
		frappe.flags[PAYMENT_HOOK_FLAG] = False

	def paid_order(self):
		order = make_order([self.pack])
		frappe.flags[PAYMENT_HOOK_FLAG] = True
		order.payment_status = "Paid"
		order.save(ignore_permissions=True)
		frappe.flags[PAYMENT_HOOK_FLAG] = False
		return order

	def signed_in_buyer(self, order):
		"""Make the order's buyer a real user on a customer company, and give the partner an admin."""
		user = make_user("_test_sp_buyer@example.com")
		customer = frappe.db.get_value("Customer", {"customer_name": "_Test SP Buyer Co"}) or (
			frappe.get_doc({"doctype": "Customer", "customer_name": "_Test SP Buyer Co"})
			.insert(ignore_permissions=True)
			.name
		)
		if not frappe.db.exists("Customer Team Member", {"user": user}):
			frappe.get_doc(
				{"doctype": "Customer Team Member", "customer": customer, "user": user, "is_admin": 1}
			).insert(ignore_permissions=True)
		admin = make_user("_test_sp_partner_admin@example.com")
		if not frappe.db.exists("Connect Partner Member", {"user": admin}):
			frappe.get_doc(
				{"doctype": "Connect Partner Member", "partner": self.partner, "user": admin, "is_admin": 1}
			).insert(ignore_permissions=True)
		order.db_set({"user": user, "customer": customer})
		return user, customer, admin

	def test_a_paid_order_goes_to_the_implementation_partner(self):
		order = self.paid_order()
		self.assertEqual(hand_over(order.name), self.partner)
		order.reload()
		self.assertEqual((order.partner, order.status), (self.partner, "Partner Assigned"))
		self.assertFalse(order.partner_auto_assigned)
		self.enqueue.assert_called_once()

	def test_the_round_robin_takes_over_only_when_switched_on(self):
		pool = make_partner("_Test RR A", starter_pack=0)
		doc = frappe.get_doc("Partner", pool)
		doc.update({"starter_pack": 1, "enabled": 1, "is_frappe_consultant": 1, "starter_pack_sequence": 1})
		doc.save(ignore_permissions=True)

		self.assertEqual(hand_over(self.paid_order().name), self.partner)
		frappe.db.set_single_value("Starter Pack Settings", "auto_assign_partners", 1)
		self.assertEqual(hand_over(self.paid_order().name), pool)

	def test_without_implemented_by_the_order_waits_and_admins_are_told(self):
		frappe.db.set_single_value("Starter Pack Settings", "implementation_partner", "")
		order = self.paid_order()
		self.assertIsNone(hand_over(order.name))
		order.reload()
		self.assertEqual((order.payment_status, order.status, order.partner), ("Paid", "New", None))
		self.notify.assert_called_once()
		self.enqueue.assert_not_called()

		frappe.db.set_single_value("Starter Pack Settings", "implementation_partner", self.partner)
		self.notify.reset_mock()
		with patch("frappe.db.commit"):  # the job commits per order; not in a test
			hand_over_waiting_orders()
		order.reload()
		self.assertEqual(order.partner, self.partner)
		self.notify.assert_not_called()  # admins were already told, at payment

	def test_unpaid_orders_are_not_handed_over(self):
		self.assertIsNone(hand_over(make_order([self.pack]).name))

	def test_the_buyer_opens_the_conversation_with_the_project(self):
		order = self.paid_order()
		hand_over(order.name)
		user, customer, admin = self.signed_in_buyer(order)

		post_opening_message(order.name)
		order.reload()
		thread = order.implementation_thread
		self.assertEqual(
			frappe.db.get_value("Connect Thread", thread, ["customer", "partner"]), (customer, self.partner)
		)
		self.assertEqual(
			set(frappe.get_all("Connect Thread Member", filters={"thread": thread}, pluck="user")), {user, admin}
		)

		hello, card = frappe.get_all(
			"Connect Message",
			filters={"thread": thread},
			fields=["sender", "message_type", "content"],
			order_by="creation asc",
		)
		self.assertEqual((hello.sender, hello.message_type), (user, "Text"))
		self.assertIn("_test_pack_a Starter Pack", hello.content)
		self.assertEqual(card.message_type, "Requirement")
		project = frappe.parse_json(card.content)
		self.assertEqual(project["looking_for"], "_test_pack_a implementation for Test Co")
		self.assertEqual(project["apps"], ["_test_pack_a"])
		self.assertEqual(project["timeline"], "30 days")

	def test_the_opening_message_is_posted_once(self):
		order = self.paid_order()
		hand_over(order.name)
		self.signed_in_buyer(order)
		post_opening_message(order.name)
		thread = frappe.db.get_value("Starter Pack Order", order.name, "implementation_thread")
		posted = frappe.db.count("Connect Message", {"thread": thread})
		post_opening_message(order.name)  # e.g. a replayed webhook queued it twice
		self.assertEqual(frappe.db.count("Connect Message", {"thread": thread}), posted)

	def test_a_guest_buyer_gets_no_thread(self):
		order = self.paid_order()
		hand_over(order.name)
		order.db_set({"user": "Guest", "customer": None})
		post_opening_message(order.name)
		self.assertIsNone(frappe.db.get_value("Starter Pack Order", order.name, "implementation_thread"))

	def test_home_lists_the_buyers_paid_orders_as_projects(self):
		paid = self.paid_order()
		hand_over(paid.name)
		user, customer, _admin = self.signed_in_buyer(paid)
		unpaid = make_order([self.pack])
		unpaid.db_set({"user": user, "customer": customer})

		frappe.set_user(user)
		try:
			projects = get_my_projects()
		finally:
			frappe.set_user("Administrator")
		self.assertIn(paid.name, [p["order"] for p in projects])
		self.assertNotIn(unpaid.name, [p["order"] for p in projects])
		project = next(p for p in projects if p["order"] == paid.name)
		self.assertEqual(project["title"], "_test_pack_a implementation for Test Co")
		self.assertEqual(project["partner"]["name"], self.partner)
		self.assertTrue(project["is_active"])

	def test_home_has_no_projects_for_a_guest(self):
		frappe.set_user("Guest")
		try:
			self.assertEqual(get_my_projects(), [])
		finally:
			frappe.set_user("Administrator")

	def test_the_sidebar_shows_projects_only_once_there_is_one(self):
		from connect.utils import get_my_context

		def context_as(user):
			frappe.set_user(user)
			try:
				return get_my_context()
			finally:
				frappe.set_user("Administrator")

		self.assertFalse(context_as("Guest")["has_projects"])

		order = self.paid_order()
		user, customer, _admin = self.signed_in_buyer(order)
		# Orders from earlier tests in this class belong to the same buyer.
		frappe.db.delete("Requirement", {"customer": customer})
		for key in ("user", "customer"):
			frappe.db.set_value("Starter Pack Order", {key: user if key == "user" else customer}, "payment_status", "Unpaid")
		self.assertFalse(context_as(user)["has_projects"])

		frappe.get_doc(
			{"doctype": "Requirement", "customer": customer, "company_name": "Test Co", "country": "India",
			 "industry": "Manufacturing"}
		).insert(ignore_permissions=True)
		self.assertEqual(context_as(user)["projects_route"], "/compare-partners")

		order.db_set("payment_status", "Paid")
		self.assertEqual(context_as(user)["projects_route"], f"/starter-pack-implementation?order={order.name}")

	def test_the_return_page_has_the_project(self):
		order = self.paid_order()
		result = get_order(order.name)
		self.assertEqual(result["project_title"], "_test_pack_a implementation for Test Co")
		self.assertEqual(result["timeline_days"], 30)


def make_user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return email
