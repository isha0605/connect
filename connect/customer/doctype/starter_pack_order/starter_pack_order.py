# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from connect.customer.doctype.customer.customer import get_customer_for_user

# Set around the one save that mirrors gateway status onto an order. Nothing
# else may move payment_status: a customer, or a Desk user, marking their own
# order Paid is exactly what this guards against.
PAYMENT_HOOK_FLAG = "in_starter_pack_payment_hook"

# Gateway Payment Request status -> Starter Pack Order payment_status.
GATEWAY_STATUS_MAP = {
	"Pending": "Unpaid",
	"Paid": "Paid",
	"Not Paid": "Failed",
	"Cancelled": "Failed",
	"Expired": "Failed",
	"Partially Refunded": "Partially Refunded",
	"Refunded": "Refunded",
}


class StarterPackOrder(Document):
	def before_insert(self):
		self.user = frappe.session.user
		if not self.customer:
			self.customer = get_customer_for_user(self.user)
		self.snapshot_packs()
		self.gst_rate = flt(frappe.db.get_single_value("Starter Pack Settings", "gst_rate"))

	def validate(self):
		if not self.is_new():
			self.validate_packs_unchanged()
		self.validate_payment_status_change()
		self.validate_partner()
		self.set_totals()

	def snapshot_packs(self):
		"""Price every line from the catalog, ignoring whatever the browser sent.

		Runs once, at creation. After that the rows are the record of what was sold,
		so a later change to a pack's price never reprices an existing order.
		"""
		seen = set()
		for row in self.packs:
			if row.starter_pack in seen:
				frappe.throw(_("{0} is in this order twice.").format(frappe.bold(row.starter_pack)))
			seen.add(row.starter_pack)

			pack = frappe.db.get_value(
				"Starter Pack",
				row.starter_pack,
				["pack_name", "price", "total_hours", "delivery_days", "is_active"],
				as_dict=True,
			)
			if not pack or not pack.is_active:
				frappe.throw(_("{0} is not available.").format(frappe.bold(row.starter_pack)))

			row.pack_name = pack.pack_name
			row.price = pack.price
			row.total_hours = pack.total_hours
			row.delivery_days = pack.delivery_days

	def validate_packs_unchanged(self):
		before = self.get_doc_before_save()
		if not before:
			return
		if [(r.starter_pack, flt(r.price)) for r in before.packs] != [
			(r.starter_pack, flt(r.price)) for r in self.packs
		]:
			frappe.throw(_("Packs and prices can't be changed after an order is placed."))

	def validate_payment_status_change(self):
		# No kickoff check here on purpose. This only ever records what the gateway
		# already did, so refusing it would leave the order out of step with money that
		# has moved. The no-refund-after-kickoff rule is enforced before the refund is
		# sent — see connect.overrides.gateway_payment_request.
		before = self.get_doc_before_save()
		old = before.payment_status if before else "Unpaid"
		if self.payment_status != old and not frappe.flags.get(PAYMENT_HOOK_FLAG):
			frappe.throw(_("Payment status is set by the payment gateway, not by hand."))

	def validate_partner(self):
		if not self.partner or not self.has_value_changed("partner"):
			return
		if self.payment_status != "Paid":
			frappe.throw(_("Assign a partner only after the order is paid."))
		# Every approved partner delivers all four packs, so approval is the whole check.
		if not frappe.db.get_value("Partner", self.partner, "starter_pack"):
			frappe.throw(
				_("{0} is not an approved Starter Pack partner.").format(frappe.bold(self.partner))
			)

	def set_totals(self):
		# Always derived from the snapshotted rows, so the total can't drift from the lines.
		self.subtotal = sum(flt(r.price) for r in self.packs)
		self.total_hours = sum(int(r.total_hours or 0) for r in self.packs)
		self.gst_amount = flt(self.subtotal * flt(self.gst_rate) / 100, self.precision("gst_amount"))
		self.amount = flt(self.subtotal + self.gst_amount, self.precision("amount"))

	def create_payment_request(self):
		"""Return the payment request to send the customer to, opening one if needed.

		An open link is reused, so paying again never creates a second one that could
		also be paid. A new link is only opened when the current one is dead — expired,
		cancelled or failed — and a dead link can no longer take money.
		"""
		if self.payment_status not in ("Unpaid", "Failed"):
			frappe.throw(_("This order has already been paid for."))

		if self.payment_request:
			current = frappe.get_doc("Gateway Payment Request", self.payment_request)
			if current.status == "Pending":
				return current

		settings = frappe.get_single("Starter Pack Settings")
		if not settings.payment_gateway:
			frappe.throw(_("Online payment isn't set up yet."))

		user = frappe.db.get_value("User", self.user, ["email", "first_name", "last_name"], as_dict=True)
		request = frappe.get_doc(
			{
				"doctype": "Gateway Payment Request",
				"gateway": settings.payment_gateway,
				"amount": self.amount,
				"currency_code": settings.currency,
				"ref_doctype": self.doctype,
				"ref_docname": self.name,
				"customer_ref": self.customer,
				"customer_email": user.email if user else None,
				"customer_phone": self.phone,
				"customer_forenames": user.first_name if user else None,
				"customer_surname": user.last_name if user else None,
			}
		).insert(ignore_permissions=True)  # before_save opens the gateway session

		# A retry after a dead link: the order is payable again.
		frappe.flags[PAYMENT_HOOK_FLAG] = True
		try:
			self.payment_request = request.name
			self.payment_status = "Unpaid"
			self.save(ignore_permissions=True)
		finally:
			frappe.flags[PAYMENT_HOOK_FLAG] = False
		return request


def on_gateway_payment_request_update(request, method=None):
	"""doc_events hook: mirror a Gateway Payment Request's status onto its order.

	Runs inside bwh_payments' save, after the gateway has already acted, so it must
	never raise: failing here would roll back bwh's record of money that moved.
	"""
	if request.ref_doctype != "Starter Pack Order" or not request.ref_docname:
		return

	order = frappe.get_doc("Starter Pack Order", request.ref_docname)
	if order.payment_request != request.name:
		# A link replaced by a newer one. It was released at the gateway first, so this
		# should never be paid — if it is, the customer paid twice and needs a refund.
		if request.status == "Paid":
			frappe.log_error(
				title="Starter Pack Order paid on a superseded link",
				message=f"{request.name} was paid, but {order.name} now uses {order.payment_request}.",
			)
		return

	payment_status = GATEWAY_STATUS_MAP.get(request.status)
	if not payment_status or payment_status == order.payment_status:
		return  # also makes a replayed webhook a no-op

	frappe.flags[PAYMENT_HOOK_FLAG] = True
	try:
		order.payment_status = payment_status
		if payment_status == "Paid" and not order.gateway_payment_id:
			order.gateway_payment_id = get_captured_payment_id(request)
		order.save(ignore_permissions=True)
	finally:
		frappe.flags[PAYMENT_HOOK_FLAG] = False


def get_captured_payment_id(request):
	"""The gateway's id for the captured payment. bwh_payments keeps only the payment
	link's id, and support asks for the payment's. Best-effort: never fails the hook."""
	if frappe.db.get_value("Payment Gateway Profile", request.gateway, "gateway_settings") != (
		"Razorpay Gateway Settings"
	):
		return None
	try:
		from bwh_payments.bwh_payments.doctype.razorpay_gateway_settings.razorpay_gateway_settings import (
			get_captured_payment_id as razorpay_captured_payment_id,
		)

		settings = frappe.get_single("Razorpay Gateway Settings")
		payment_id = razorpay_captured_payment_id(settings.get_payment_link(request.order_ref))
	except Exception:
		# e.g. treat_authorised_as_paid: the link is Paid but nothing is captured yet.
		frappe.clear_messages()
		frappe.log_error(title=f"Could not read the payment id for {request.name}")
		return None

	request.db_set("gateway_transaction_ref", payment_id, update_modified=False)
	return payment_id


def checkout(packs, company_name, phone=None, terms_accepted=0):
	"""Place an order for the given pack keys and open its payment. Returns where to
	send the customer to pay.

	Takes pack keys only. Prices and totals are worked out server-side from the catalog.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Log in to check out."), frappe.PermissionError)
	if not frappe.utils.cint(terms_accepted):
		frappe.throw(_("Accept the terms to continue."))

	pack_keys = frappe.parse_json(packs) if isinstance(packs, str) else packs
	if not pack_keys:
		frappe.throw(_("Pick at least one pack."))

	order = frappe.get_doc(
		{
			"doctype": "Starter Pack Order",
			"company_name": company_name,
			"phone": phone,
			"terms_accepted": 1,
			"packs": [{"starter_pack": key} for key in pack_keys],
		}
	).insert(ignore_permissions=True)

	request = order.create_payment_request()
	return {"order": order.name, "amount": order.amount, "payment_url": request.order_url}


def get_order(order=None, payment_request=None):
	"""An order's status for the page the gateway sends the customer back to.

	Razorpay's return URL carries the Gateway Payment Request's name (`reference_id`),
	not the order's, so either identifies it. Re-reads the payment status from the
	gateway rather than trusting the redirect, which anyone can open by hand.
	"""
	if not order and payment_request:
		order = frappe.db.get_value("Starter Pack Order", {"payment_request": payment_request})
		if not order:
			# The request exists but is no longer the order's current one, or never was.
			order = frappe.db.get_value(
				"Gateway Payment Request",
				{"name": payment_request, "ref_doctype": "Starter Pack Order"},
				"ref_docname",
			)
	if not order:
		frappe.throw(_("Order not found"), frappe.DoesNotExistError)

	doc = get_own_order(order)
	if doc.payment_request and doc.payment_status == "Unpaid":
		frappe.get_doc("Gateway Payment Request", doc.payment_request).sync_status()
		doc.reload()

	return {
		"order": doc.name,
		"payment_status": doc.payment_status,
		"status": doc.status,
		"subtotal": doc.subtotal,
		"gst_rate": doc.gst_rate,
		"gst_amount": doc.gst_amount,
		"amount": doc.amount,
		"total_hours": doc.total_hours,
		"packs": [
			{"pack_name": r.pack_name, "price": r.price, "total_hours": r.total_hours} for r in doc.packs
		],
	}


def pay(order):
	"""Send the customer back to pay an order they already placed — e.g. after a
	payment link expired. Reuses an open link rather than opening a second one."""
	doc = get_own_order(order)
	request = doc.create_payment_request()
	return {"order": doc.name, "amount": doc.amount, "payment_url": request.order_url}


def get_own_order(order):
	doc = frappe.get_doc("Starter Pack Order", order)
	if doc.user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return doc
