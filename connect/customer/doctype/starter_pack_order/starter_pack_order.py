# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from connect.customer.doctype.customer.customer import get_customer_for_user

# Set by the payment webhook handler around its save. Nothing else may move
# payment_status: a customer, or a Desk user, marking their own order Paid is
# exactly what this guards against.
PAYMENT_HOOK_FLAG = "in_starter_pack_payment_hook"


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
		before = self.get_doc_before_save()
		old = before.payment_status if before else "Unpaid"
		if self.payment_status == old:
			return
		if not frappe.flags.get(PAYMENT_HOOK_FLAG):
			frappe.throw(_("Payment status is set by the payment gateway, not by hand."))
		if self.payment_status == "Refunded" and self.kickoff_date:
			frappe.throw(_("This order can't be refunded: the implementation has already kicked off."))

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
