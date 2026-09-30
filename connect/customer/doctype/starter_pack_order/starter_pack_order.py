# Copyright (c) 2026
# For license information, please see license.txt

import hmac
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime, get_system_timezone, now_datetime

from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.customer.doctype.starter_pack_order.partner_rotation import assign_partner

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
		if not self.customer and self.user != "Guest":
			self.customer = get_customer_for_user(self.user)
		self.access_key = frappe.generate_hash(length=32)
		self.snapshot_packs()
		self.gst_rate = flt(frappe.get_cached_doc("Starter Pack Settings").gst_rate)

	def validate(self):
		if not self.is_new():
			self.validate_packs_unchanged()
		self.validate_payment_status_change()
		self.set_paid_on()
		self.validate_partner()
		self.set_partner_assignment()
		self.set_totals()

	def snapshot_packs(self):
		"""Price every line from the catalog, ignoring whatever the browser sent.

		Runs once, at creation. After that the rows are the record of what was sold,
		so a later change to a pack's price never reprices an existing order.
		"""
		catalog = {
			p.name: p
			for p in frappe.get_all(
				"Starter Pack",
				filters={"name": ["in", [row.starter_pack for row in self.packs]]},
				fields=["name", "pack_name", "price", "total_hours", "delivery_days", "is_active"],
			)
		}
		seen = set()
		for row in self.packs:
			if row.starter_pack in seen:
				frappe.throw(_("{0} is in this order twice.").format(frappe.bold(row.starter_pack)))
			seen.add(row.starter_pack)

			pack = catalog.get(row.starter_pack)
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

	def set_paid_on(self):
		# When the payment first landed. Kept through a later refund: the Confirmed page's
		# activity and support both want to know when the money came in.
		if self.payment_status == "Paid" and not self.paid_on:
			self.paid_on = now_datetime()

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

	def set_partner_assignment(self):
		"""Record when and how the partner was set. Only the round robin sets
		flags.auto_assigned (see partner_rotation); a partner set by hand in Desk is
		recorded as such and leaves the rotation's pointer alone."""
		if not self.has_value_changed("partner"):
			return
		if self.partner:
			self.partner_assigned_on = now_datetime()
			self.partner_auto_assigned = 1 if self.flags.auto_assigned else 0
			if self.status == "New":
				self.status = "Partner Assigned"
		else:
			self.partner_assigned_on = None
			self.partner_auto_assigned = 0
			if self.status == "Partner Assigned":
				self.status = "New"

	def set_totals(self):
		# Always derived from the snapshotted rows, so the total can't drift from the lines.
		self.subtotal = sum(flt(r.price) for r in self.packs)
		self.total_hours = sum(cint(r.total_hours) for r in self.packs)
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

		settings = frappe.get_cached_doc("Starter Pack Settings")
		if not settings.payment_gateway:
			frappe.throw(_("Online payment isn't set up yet."))

		forenames, _sep, surname = (self.buyer_name or "").strip().partition(" ")
		request = frappe.get_doc(
			{
				"doctype": "Gateway Payment Request",
				"gateway": settings.payment_gateway,
				"amount": self.amount,
				"currency_code": settings.currency,
				"ref_doctype": self.doctype,
				"ref_docname": self.name,
				"customer_ref": self.customer,
				# Whoever checkout says is paying — sent to Razorpay as the customer.
				"customer_email": self.buyer_email,
				"customer_phone": self.phone,
				"customer_forenames": forenames or None,
				"customer_surname": surname or None,
			}
		).insert(ignore_permissions=True)  # before_save opens the gateway session

		# A retry after a dead link: the order is payable again.
		self.payment_request = request.name
		self.payment_status = "Unpaid"
		save_as_payment_hook(self)
		return request


def save_as_payment_hook(order):
	"""Save an order whose payment_status the gateway moved — the one save allowed to."""
	frappe.flags[PAYMENT_HOOK_FLAG] = True
	try:
		order.save(ignore_permissions=True)
	finally:
		frappe.flags[PAYMENT_HOOK_FLAG] = False


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

	order.payment_status = payment_status
	if payment_status == "Paid" and not order.gateway_payment_id:
		order.gateway_payment_id = get_captured_payment_id(request)
	save_as_payment_hook(order)

	if payment_status == "Paid" and not order.partner:
		assign_partner(order.name)  # never raises; leaves the order unassigned on failure


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


def checkout(packs, company_name, phone=None, terms_accepted=0, buyer_name=None, buyer_email=None):
	"""Place an order for the given pack keys and open its payment. Returns where to
	send the customer to pay, and the order's access key.

	Anyone can buy, logged in or not: sign-in is a mock today, so the buyer is whoever the
	checkout form names. No account is made for them — their name and email are kept on the
	order and its payment request, and the access key is what lets their browser read the
	order back after paying.

	Takes pack keys only. Prices and totals are worked out server-side from the catalog.
	"""
	buyer_name = (buyer_name or "").strip()
	buyer_email = (buyer_email or "").strip()
	if not buyer_name:
		frappe.throw(_("Enter your name."))
	if not buyer_email:
		frappe.throw(_("Enter your email."))
	frappe.utils.validate_email_address(buyer_email, throw=True)
	if not frappe.utils.cint(terms_accepted):
		frappe.throw(_("Accept the terms to continue."))

	pack_keys = frappe.parse_json(packs)
	if not pack_keys:
		frappe.throw(_("Pick at least one pack."))

	order = frappe.get_doc(
		{
			"doctype": "Starter Pack Order",
			"buyer_name": buyer_name,
			"buyer_email": buyer_email,
			"company_name": company_name,
			"phone": phone,
			"terms_accepted": 1,
			"packs": [{"starter_pack": key} for key in pack_keys],
		}
	).insert(ignore_permissions=True)

	return payment_response(order, order.create_payment_request())


def payment_response(order, request):
	return {
		"order": order.name,
		"key": order.access_key,
		"payment_request": request.name,
		"amount": order.amount,
		"payment_url": request.order_url,
	}


def get_order(order=None, payment_request=None, key=None):
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

	doc = get_own_order(order, key)
	if doc.payment_request and doc.payment_status == "Unpaid":
		frappe.get_doc("Gateway Payment Request", doc.payment_request).sync_status()
		doc.reload()

	return {
		"order": doc.name,
		"company_name": doc.company_name,
		"payment_status": doc.payment_status,
		"payment_request": doc.payment_request,
		"status": doc.status,
		"created_on": with_timezone(doc.creation),
		"paid_on": with_timezone(doc.paid_on),
		"partner_assigned_on": with_timezone(doc.partner_assigned_on),
		"subtotal": doc.subtotal,
		"gst_rate": doc.gst_rate,
		"gst_amount": doc.gst_amount,
		"amount": doc.amount,
		"total_hours": doc.total_hours,
		"kickoff_date": doc.kickoff_date,
		"partner": get_assigned_partner(doc.partner) if doc.partner else None,
		"packs": [
			{
				"starter_pack": r.starter_pack,
				"pack_name": r.pack_name,
				"price": r.price,
				"total_hours": r.total_hours,
				"delivery_days": r.delivery_days,
			}
			for r in doc.packs
		],
	}


def with_timezone(value):
	"""A stored datetime as ISO 8601 with the site's offset. Frappe keeps datetimes in the
	system time zone without saying so, and a browser elsewhere would read them as its own."""
	if not value:
		return None
	return get_datetime(value).replace(tzinfo=ZoneInfo(get_system_timezone())).isoformat()


def get_assigned_partner(partner):
	"""The partner card on the Confirmed page: the directory preview, plus the review count
	and the industries their profile shows, so both pages describe them the same way."""
	from connect.partner.doctype.partner.partner import _compute_display_industries, get_partner_preview

	preview = get_partner_preview(partner)
	stories = frappe.get_all(
		"Partner Success Story",
		filters={"parent": partner, "parenttype": "Partner", "parentfield": "success_stories"},
		fields=["category"],
	)
	preview["industries"] = _compute_display_industries(preview.industry, stories)
	preview["review_count"] = frappe.db.count("Partner Review", {"partner": partner})
	return preview


def pay(order, key=None):
	"""Send the customer back to pay an order they already placed — e.g. after a
	payment link expired. Reuses an open link rather than opening a second one."""
	doc = get_own_order(order, key)
	return payment_response(doc, doc.create_payment_request())


def get_own_order(order, key=None):
	"""The order, if the caller may see it: with its access key (a guest's browser holds
	it), as the logged-in user who placed it, or as a System Manager."""
	doc = frappe.get_doc("Starter Pack Order", order)
	user = frappe.session.user
	if key and doc.access_key and hmac.compare_digest(str(key), doc.access_key):
		return doc
	if user != "Guest" and doc.user == user:
		return doc
	if "System Manager" in frappe.get_roles():
		return doc
	frappe.throw(_("Not permitted"), frappe.PermissionError)
