# Copyright (c) 2026
# For license information, please see license.txt

"""What happens to a Starter Pack Order once it's paid.

With round robin switched on (Starter Pack Settings), each paid order goes to the next Frappe
consultant (see connect.partner.consultants). With it off, or with no consultant enabled,
it goes to the Implemented By partner. Either way, once the order has a partner, the buyer's
opening message to them is posted in their chat thread: a hello and a card with the project.

A consultant who stops hands their open orders on (reassign). The order's thread stays: the
next consultant joins it, so the conversation carries on where it was.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

from connect.api.contact import _ensure_thread_member
from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.customer.doctype.requirement.requirement import get_requirement_snapshot
from connect.customer.doctype.starter_pack_order.partner_rotation import (
	assign_partner,
	get_pool,
	lock_rotation,
	pick_next,
	tell_admins,
	write_pointer,
)
from connect.permissions import _get_partner_admin

SETTINGS = "Starter Pack Settings"
SAVEPOINT = "starter_pack_implementation_partner"
REASSIGN_SAVEPOINT = "starter_pack_reassign"


def hand_over(order_name, tell_admins_if_unassigned=True):
	"""Give a paid order its partner and queue the buyer's opening message to them. Returns the
	order's partner afterwards, or None if it's still unassigned.

	Never raises: it runs inside the payment hook, and a partner that couldn't be set must
	never undo the record of a payment.
	"""
	round_robin = cint(frappe.db.get_single_value(SETTINGS, "auto_assign_partners"))
	if round_robin and get_pool():
		partner = assign_partner(order_name, tell_admins_if_unassigned)
	else:
		partner = give_to_implementation_partner(order_name, tell_admins_if_unassigned)
		if partner and round_robin and tell_admins_if_unassigned:
			tell_admins(
				frappe._dict(name=order_name),
				_("{0} went to {1}: no Frappe consultant is enabled.").format(order_name, partner),
			)

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


def reassign(order_name):
	"""Give an open order to the next consultant in turn, because its own has stopped, or to
	the Implemented By partner if there's no one else. Returns the new partner, or None.
	Never raises: a consultant's role being taken away must not fail on one order."""
	frappe.db.savepoint(REASSIGN_SAVEPOINT)
	try:
		pointer = lock_rotation()
		order = frappe.get_doc("Starter Pack Order", order_name, for_update=True)
		pool = [p for p in get_pool() if p.name != order.partner]
		partner = pick_next(pool, pointer)
		if partner:
			order.partner = partner.name
			order.flags.auto_assigned = True
			order.save(ignore_permissions=True)
			write_pointer(partner)
			return partner.name

		fallback = frappe.db.get_single_value(SETTINGS, "implementation_partner")
		if fallback and fallback != order.partner:
			order.partner = fallback
			order.save(ignore_permissions=True)
			return fallback
	except Exception:
		frappe.db.rollback(save_point=REASSIGN_SAVEPOINT)
		frappe.log_error(title=f"Could not hand {order_name} to another consultant")

	tell_admins(
		frappe._dict(name=order_name),
		_("{0} needs a new partner: its consultant stopped and it couldn't be handed on.").format(order_name),
	)
	return None


def join_thread(order):
	"""When an order's partner changes after the buyer's thread was opened, the new partner's
	admin joins that thread, so the conversation and its history carry on. A thread's partner
	can't change once it's created (Connect Thread), so the thread keeps its first name."""
	if not order.implementation_thread or not order.partner:
		return
	admin = _get_partner_admin(order.partner)
	if not admin or frappe.db.exists(
		"Connect Thread Member", {"thread": order.implementation_thread, "user": admin, "is_removed": 0}
	):
		return
	member = frappe.db.get_value(
		"Connect Thread Member", {"thread": order.implementation_thread, "user": admin}, "name"
	)
	if member:
		frappe.db.set_value("Connect Thread Member", member, {"is_removed": 0, "removed_on": None})
	else:
		_ensure_thread_member(order.implementation_thread, admin, "Partner", frappe.session.user)
	frappe.get_doc("Connect Thread", order.implementation_thread).post_system_message(
		_("{0} is now looking after this project.").format(
			frappe.db.get_value("Partner", order.partner, "partner_name") or order.partner
		)
	)


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
