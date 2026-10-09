# Copyright (c) 2026
# For license information, please see license.txt

"""Round-robin assignment of paid Starter Pack Orders.

There are two rotations, sharing this code: PARTNERS hands an order to an approved Starter
Pack partner (off for now: Auto-assign in Starter Pack Settings), and CONSULTANTS hands an
order Frappe delivers to one of its Frappe Consultants.

A rotation is an ordered list — the enabled members of its pool, by their rotation order,
then name — plus a pointer to the last one it picked, kept in Starter Pack Settings. The
next pick is the first one after the pointer, wrapping back to the start.

The pointer records where the last pick stood in that order (its rotation order and
name), not a link to the partner. So it keeps working when that partner is later
disabled, taken out of the pool or deleted: the next pick is whoever now comes after
that spot. Only automatic picks move it; setting a partner by hand in Desk doesn't, and
nor does a returning customer going back to the consultant they already have.
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


class Rotation:
	"""Where one rotation's pool and pointer live."""

	def __init__(self, doctype, filters, sequence_field, last_name_field, last_sequence_field):
		self.doctype = doctype
		self.filters = filters
		self.sequence_field = sequence_field
		self.last_name_field = last_name_field
		self.last_sequence_field = last_sequence_field


PARTNERS = Rotation(
	"Partner", {"starter_pack": 1, "enabled": 1}, "starter_pack_sequence", "rr_last_partner", "rr_last_sequence"
)
CONSULTANTS = Rotation(
	"Frappe Consultant", {"enabled": 1}, "rotation_order", "rr_last_consultant", "rr_last_consultant_sequence"
)


def get_pool(rotation=PARTNERS):
	"""The rotation's members in turn order, as {name, sequence} rows."""
	rows = frappe.get_all(
		rotation.doctype,
		filters=rotation.filters,
		fields=["name", f"{rotation.sequence_field} as sequence"],
	)
	return sorted(rows, key=lambda p: rotation_key(p.sequence, p.name))


def pick_next(pool, pointer):
	"""The partner after `pointer` — a (rotation order, name) pair, or None before the
	first automatic pick — wrapping to the start. None only when the pool is empty."""
	if not pool:
		return None
	if pointer:
		last = rotation_key(*pointer)
		for partner in pool:
			if rotation_key(partner.sequence, partner.name) > last:
				return partner
	return pool[0]


def read_pointer(rotation=PARTNERS):
	"""(rotation order, name) of the rotation's last automatic pick, or None. An unlocked read
	for looking at the rotation — assigning uses the pointer lock_rotation reads instead."""
	name = frappe.db.get_single_value(SETTINGS, rotation.last_name_field, cache=False)
	if not name:
		return None
	return (frappe.db.get_single_value(SETTINGS, rotation.last_sequence_field, cache=False), name)


def write_pointer(picked, rotation=PARTNERS):
	frappe.db.set_single_value(
		SETTINGS,
		{rotation.last_name_field: picked.name, rotation.last_sequence_field: cint(picked.sequence)},
	)


def lock_rotation(rotation=PARTNERS):
	"""Take the rotation's row lock until this transaction commits, so two payments landing
	at once can't both read the same pointer and hand out the same pick. Returns the
	pointer as read under that lock, in read_pointer's shape."""
	pointer = _select_pointer_for_update(rotation)
	if rotation.last_sequence_field not in pointer:
		# Never used yet, so there's no row to lock. The rotation patch creates it; this only
		# covers a site where it hasn't run. (get_single_value can't tell a missing Int row
		# from 0, hence reading tabSingles directly.)
		frappe.db.set_single_value(SETTINGS, rotation.last_sequence_field, 0)
		pointer = _select_pointer_for_update(rotation)
	if not pointer.get(rotation.last_name_field):
		return None
	return (cint(pointer[rotation.last_sequence_field]), pointer[rotation.last_name_field])


def _select_pointer_for_update(rotation):
	"""Both pointer fields in one locked read, as {field: value}."""
	Singles = frappe.qb.DocType("Singles")
	fields = [rotation.last_name_field, rotation.last_sequence_field]
	return dict(
		(
			frappe.qb.from_(Singles)
			.select(Singles.field, Singles.value)
			.where((Singles.doctype == SETTINGS) & Singles.field.isin(fields))
			.for_update()
		).run()
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
		pointer = lock_rotation()
		order = frappe.get_doc("Starter Pack Order", order_name, for_update=True)
		if order.partner or order.payment_status != "Paid":
			# Already assigned — a replayed webhook, or someone set it by hand first.
			return order.partner or None

		partner = pick_next(get_pool(), pointer)
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


CONSULTANT_SAVEPOINT = "starter_pack_consultant_rotation"


def assign_consultant(order_name, tell_admins_if_unassigned=True, leaving=None):
	"""Give a paid order Frappe delivers its Frappe Consultant: the one a returning customer
	already has, else the next in turn. Returns the order's consultant afterwards, or None.

	`leaving` is a consultant who is stopping: their orders go to someone else. Never raises,
	for the same reason assign_partner doesn't.
	"""
	frappe.db.savepoint(CONSULTANT_SAVEPOINT)
	try:
		pointer = lock_rotation(CONSULTANTS)
		order = frappe.get_doc("Starter Pack Order", order_name, for_update=True)
		if order.payment_status != "Paid" or (order.consultant and order.consultant != leaving):
			return order.consultant or None

		pool = [c for c in get_pool(CONSULTANTS) if c.name != leaving]
		returning_to = previous_consultant(order, pool)
		consultant = returning_to or pick_next(pool, pointer)
		if not consultant:
			# Only worth saying once Frappe has consultants at all: before that, Frappe's
			# admin taking the chat is simply how it works.
			if tell_admins_if_unassigned and frappe.db.count("Frappe Consultant"):
				tell_admins(
					order,
					_("{0} has no Frappe consultant: none is enabled. Its chat is with Frappe's admin.").format(
						order.name
					),
				)
			if leaving:
				order.consultant = None
				order.save(ignore_permissions=True)
			return None

		order.consultant = consultant.name
		order.save(ignore_permissions=True)
		if not returning_to:
			write_pointer(consultant, CONSULTANTS)
		return consultant.name
	except Exception:
		frappe.db.rollback(save_point=CONSULTANT_SAVEPOINT)
		frappe.log_error(title=f"Could not give {order_name} a Frappe consultant")
		if tell_admins_if_unassigned:
			tell_admins(
				frappe._dict(name=order_name),
				_("{0} is paid but giving it a Frappe consultant failed. See the Error Log.").format(order_name),
			)
		return None


def previous_consultant(order, pool):
	"""The consultant a returning customer already has, if they're still in the pool, so the
	customer stays in the one chat they know. The customer's company counts, not just the
	buyer: a colleague's earlier order counts too."""
	if not pool:
		return None
	if order.customer:
		owner = {"customer": order.customer}
	elif order.user and order.user != "Guest":
		owner = {"user": order.user}
	else:
		return None
	by_name = {c.name: c for c in pool}
	earlier = frappe.get_all(
		"Starter Pack Order",
		filters={**owner, "name": ["!=", order.name], "consultant": ["in", list(by_name)]},
		order_by="creation desc",
		pluck="consultant",
		limit=1,
	)
	return by_name[earlier[0]] if earlier else None


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
	frappe.get_doc("Starter Pack Order", order.name).add_comment("Info", message)
