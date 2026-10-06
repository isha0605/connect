# Copyright (c) 2026
# For license information, please see license.txt

"""What happens to a Starter Pack Order once it's paid.

Until round robin assignment is switched on (Starter Pack Settings), every paid order goes to
one partner, the Implemented By partner. Either way, once the order has a partner, the buyer's
opening message to them is posted in their chat thread: a hello and a card with the project.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

from connect.api.contact import _ensure_thread_member
from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.customer.doctype.requirement.requirement import get_requirement_snapshot
from connect.customer.doctype.starter_pack_order.partner_rotation import assign_partner, tell_admins
from connect.permissions import _get_partner_admin

SETTINGS = "Starter Pack Settings"
SAVEPOINT = "starter_pack_implementation_partner"


def hand_over(order_name, tell_admins_if_unassigned=True):
	"""Give a paid order its partner and queue the buyer's opening message to them. Returns the
	order's partner afterwards, or None if it's still unassigned.

	Never raises: it runs inside the payment hook, and a partner that couldn't be set must
	never undo the record of a payment.
	"""
	if cint(frappe.db.get_single_value(SETTINGS, "auto_assign_partners")):
		partner = assign_partner(order_name, tell_admins_if_unassigned)
	else:
		partner = give_to_implementation_partner(order_name, tell_admins_if_unassigned)

	if partner:
		# After commit, so a failure here can't touch the payment, and the job sees the partner.
		frappe.enqueue(post_opening_message, order_name=order_name, enqueue_after_commit=True)
	return partner


def give_to_implementation_partner(order_name, tell_admins_if_unassigned=True):
	"""Set a paid, unassigned order's partner to the Implemented By partner. Never raises."""
	partner = frappe.db.get_single_value(SETTINGS, "implementation_partner")
	if not partner:
		if tell_admins_if_unassigned:
			tell_admins(
				frappe._dict(name=order_name),
				_("{0} is paid but has no partner: set Implemented By in Starter Pack Settings.").format(
					order_name
				),
			)
		return None

	frappe.db.savepoint(SAVEPOINT)
	try:
		order = frappe.get_doc("Starter Pack Order", order_name, for_update=True)
		if order.partner or order.payment_status != "Paid":
			return order.partner or None
		order.partner = partner
		order.save(ignore_permissions=True)
		return partner
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.log_error(title=f"Could not give {order_name} to its Starter Pack partner")
		if tell_admins_if_unassigned:
			tell_admins(
				frappe._dict(name=order_name),
				_("{0} is paid but setting its partner failed. See the Error Log.").format(order_name),
			)
		return None


def hand_over_waiting_orders():
	"""Hourly: give a partner to any paid order still without one — say it was paid before
	Implemented By was set. Admins were told once, at payment; this doesn't tell them again."""
	for name in frappe.get_all(
		"Starter Pack Order",
		filters={"payment_status": "Paid", "partner": ["is", "not set"], "status": "New"},
		order_by="creation asc",
		pluck="name",
	):
		hand_over(name, tell_admins_if_unassigned=False)
		frappe.db.commit()


@frappe.whitelist(methods=["POST"])
def assign_now(order):
	"""The Desk "Assign partner" button: hand one paid order over now."""
	frappe.only_for("System Manager")
	partner = hand_over(order, tell_admins_if_unassigned=False)
	if not partner:
		frappe.throw(_("No partner to give this order to. Set Implemented By in Starter Pack Settings."))
	return partner


def post_opening_message(order_name):
	"""Post the buyer's first messages to their partner, once: a hello and the project card.

	Only for a buyer signed in with a real account. A thread is between a customer company and
	a partner, and the mock sign-in creates neither a user nor a company.
	"""
	order = frappe.get_doc("Starter Pack Order", order_name)
	if order.implementation_thread or not order.partner or order.payment_status != "Paid":
		return
	if order.user in (None, "", "Guest"):
		return
	customer = order.customer or get_customer_for_user(order.user)
	if not customer:
		return
	user = order.user

	try:
		thread = get_or_open_thread(customer, order.partner, user)
		for message in opening_messages(order, customer):
			frappe.get_doc({"doctype": "Connect Message", "thread": thread, "sender": user, **message}).insert(
				ignore_permissions=True
			)
		order.db_set("implementation_thread", thread)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title=f"Could not post the opening message for {order_name}")


def get_or_open_thread(customer, partner, user):
	"""The customer's thread with the partner — the one Contact Partner opens — reopened if
	it was closed, with the buyer and the partner's admin as members."""
	thread = frappe.db.get_value("Connect Thread", {"customer": customer, "partner": partner}, "name")
	if thread:
		if frappe.db.get_value("Connect Thread", thread, "status") == "Closed":
			doc = frappe.get_doc("Connect Thread", thread)
			doc.status = "Open"
			doc.save(ignore_permissions=True)
	else:
		thread = (
			frappe.get_doc({"doctype": "Connect Thread", "customer": customer, "partner": partner})
			.insert(ignore_permissions=True)
			.name
		)

	_ensure_thread_member(thread, user, "Customer", user)
	partner_admin = _get_partner_admin(partner)
	if partner_admin:
		_ensure_thread_member(thread, partner_admin, "Partner", user)
	return thread


def opening_messages(order, customer):
	"""The hello, then a Requirement card: what the buyer told us about their company, with
	the project in place of what they're looking for. Messaging renders that card already."""
	card = get_requirement_snapshot(customer) or {}
	card.update(
		{
			"company_name": order.company_name or card.get("company_name"),
			"looking_for": project_title(order),
			"apps": pack_names(order),
			"timeline": _("{0} days").format(timeline_days(order)),
		}
	)
	return [
		{
			"message_type": "Text",
			"content": _("Hi — we have just bought the {0}. Here is where we are today.").format(
				bought_packs(order)
			),
		},
		{"message_type": "Requirement", "content": json.dumps({k: v for k, v in card.items() if v})},
	]


def pack_names(order):
	return [row.pack_name for row in order.packs]


def project_title(order):
	"""e.g. "Accounts, Sales, Purchase, Stock implementation for Northwind"."""
	return _("{0} implementation for {1}").format(", ".join(pack_names(order)), order.company_name)


def bought_packs(order):
	"""e.g. "Accounts, Sales, Purchase, Stock Starter Pack", or "HR and Payroll Starter Packs".
	Pack names have commas of their own, so several are joined with "and"."""
	names = pack_names(order)
	if len(names) == 1:
		return _("{0} Starter Pack").format(names[0])
	return _("{0} Starter Packs").format(" and ".join(names))


def timeline_days(order):
	"""The packs are delivered side by side, so the project takes as long as the longest one."""
	return max((cint(row.delivery_days) for row in order.packs), default=0)
