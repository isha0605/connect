# Copyright (c) 2026
# For license information, please see license.txt

"""Round-robin assignment of paid Starter Pack Orders to approved Starter Pack partners.

The rotation is an ordered list — enabled partners with Starter Pack Partner ticked, by
their Starter Pack Rotation Order, then name — plus a pointer to the last partner the
rotation picked, kept in Starter Pack Settings. The next pick is the first partner after
the pointer, wrapping back to the start.

The pointer records where the last pick stood in that order (its rotation order and
name), not a link to the partner. So it keeps working when that partner is later
disabled, taken out of the pool or deleted: the next pick is whoever now comes after
that spot. Only automatic picks move it; setting a partner by hand in Desk doesn't.
"""

import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.user import get_users_with_role

SETTINGS = "Starter Pack Settings"
SAVEPOINT = "starter_pack_partner_rotation"

# A pool partner with no rotation order can only come from a direct database edit —
# saving a Partner fills one in. They still take part, after everyone numbered.
UNNUMBERED = 10**9


def rotation_key(sequence, name):
	sequence = cint(sequence)
	return (sequence if sequence > 0 else UNNUMBERED, name or "")


def get_pool():
	partners = frappe.get_all(
		"Partner",
		filters={"starter_pack": 1, "enabled": 1},
		fields=["name", "starter_pack_sequence"],
	)
	return sorted(partners, key=lambda p: rotation_key(p.starter_pack_sequence, p.name))


def pick_next(pool, pointer):
	"""The partner after `pointer` — a (rotation order, name) pair, or None before the
	first automatic pick — wrapping to the start. None only when the pool is empty."""
	if not pool:
		return None
	if pointer:
		last = rotation_key(*pointer)
		for partner in pool:
			if rotation_key(partner.starter_pack_sequence, partner.name) > last:
				return partner
	return pool[0]


def read_pointer():
	name = frappe.db.get_single_value(SETTINGS, "rr_last_partner", cache=False)
	if not name:
		return None
	return (frappe.db.get_single_value(SETTINGS, "rr_last_sequence", cache=False), name)


def write_pointer(partner):
	frappe.db.set_single_value(SETTINGS, "rr_last_partner", partner.name)
	frappe.db.set_single_value(SETTINGS, "rr_last_sequence", cint(partner.starter_pack_sequence))


def lock_rotation():
	"""Take the rotation's row lock until this transaction commits, so two payments landing
	at once can't both read the same pointer and hand out the same partner."""
	if _select_pointer_row_for_update():
		return
	# Never used yet, so there's no row to lock. The rotation patch creates it; this only
	# covers a site where it hasn't run. (get_single_value can't tell a missing Int row
	# from 0, hence the raw query.)
	frappe.db.set_single_value(SETTINGS, "rr_last_sequence", 0)
	_select_pointer_row_for_update()


def _select_pointer_row_for_update():
	return frappe.db.sql(
		"select value from `tabSingles` where doctype = %s and field = 'rr_last_sequence' for update",
		SETTINGS,
	)


def assign_partner(order_name, tell_admins_if_unassigned=True):
	"""Give a paid, unassigned order the next partner in the rotation. Returns the order's
	partner afterwards, or None if it's still unassigned.

	Never raises: it runs inside the payment hook, after the money has moved, and a
	missing partner must never undo the record of a payment. The pick and the pointer
	move share one savepoint, so either both happen or neither does.
	"""
	frappe.db.savepoint(SAVEPOINT)
	try:
		lock_rotation()
		order = frappe.get_doc("Starter Pack Order", order_name, for_update=True)
		if order.partner or order.payment_status != "Paid":
			# Already assigned — a replayed webhook, or someone set it by hand first.
			return order.partner or None

		partner = pick_next(get_pool(), read_pointer())
		if not partner:
			if tell_admins_if_unassigned:
				tell_admins(
					order,
					_("{0} is paid but has no partner: no Starter Pack partner is approved and enabled.").format(
						order.name
					),
				)
			return None

		order.partner = partner.name
		order.flags.auto_assigned = True
		order.save(ignore_permissions=True)
		write_pointer(partner)
		return partner.name
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.log_error(title=f"Could not assign a Starter Pack partner to {order_name}")
		if tell_admins_if_unassigned:
			tell_admins(
				frappe._dict(name=order_name),
				_("{0} is paid but assigning its partner failed. See the Error Log.").format(order_name),
			)
		return None


def tell_admins(order, message):
	"""A bell notification for every System Manager, plus a note on the order's timeline,
	so an order left without a partner is noticed rather than found later. Never raises,
	for the same reason assign_partner doesn't."""
	try:
		_tell_admins(order, message)
	except Exception:
		frappe.log_error(title=f"Could not tell admins about {order.name}", message=message)


def _tell_admins(order, message):
	# get_users_with_role leaves Administrator out, and on a small site they can be the
	# only admin there is, so they're added back.
	admins = sorted(set(get_users_with_role("System Manager")) | {"Administrator"})
	if admins:
		from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

		enqueue_create_notification(
			admins,
			{
				"type": "Alert",
				"document_type": "Starter Pack Order",
				"document_name": order.name,
				"subject": message,
			},
		)
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": "Starter Pack Order",
			"reference_name": order.name,
			"content": message,
		}
	).insert(ignore_permissions=True)


def assign_waiting_orders():
	"""Hourly: give a partner to any paid order still without one — say it was paid while
	nobody was approved. Admins were told once, at payment; this doesn't tell them again."""
	for name in frappe.get_all(
		"Starter Pack Order",
		filters={"payment_status": "Paid", "partner": ["is", "not set"], "status": "New"},
		order_by="creation asc",
		pluck="name",
	):
		assign_partner(name, tell_admins_if_unassigned=False)
		frappe.db.commit()


@frappe.whitelist()
def assign_now(order):
	"""The Desk "Assign partner" button: run the rotation for one order now."""
	frappe.only_for("System Manager")
	partner = assign_partner(order, tell_admins_if_unassigned=False)
	if not partner:
		frappe.throw(_("No Starter Pack partner is approved and enabled to assign."))
	return partner
