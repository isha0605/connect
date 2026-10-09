# Copyright (c) 2026
# For license information, please see license.txt

"""Frappe consultants: the Frappe staff who deliver Starter Packs.

Frappe is the partner on every Starter Pack order for now; the consultant is the person
inside Frappe doing the work. A System Manager gives a User the Frappe Consultant role, and
that's all it takes:

- a Frappe Consultant record is made for them, and the Starter Pack rotation hands them
  orders in turn (partner_rotation.CONSULTANTS);
- they join the Frappe partner's team, so Messaging shows them the partner side. They see
  only the threads they're in: each consultant has their own thread with each buyer
  (Connect Thread.consultant);
- they're never a Partner, so nothing about them shows where buyers browse partners.

Taking the role away (or disabling the User) switches the record off: their open orders and
those orders' threads go to the next consultant, and they leave the Frappe team. Giving the
role back switches them on again. The record is never deleted, so past orders keep it.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from connect.roles import CONSULTANT_ROLE, PARTNER_ROLE

CONSULTANT = "Frappe Consultant"
SETTINGS = "Starter Pack Settings"
# Orders still being delivered: the ones a leaving consultant hands over.
OPEN_STATUSES = ["New", "Partner Assigned", "In Progress"]


def validate_user(doc, method=None):
	"""User validate. A consultant sees Messaging from Frappe's side, and someone on a customer
	team would keep seeing it as a buyer (customer membership wins), so one person can't be
	both: the role is refused until they leave that team."""
	if doc.name in ("Administrator", "Guest") or CONSULTANT_ROLE not in {row.role for row in doc.roles}:
		return
	customer = frappe.db.get_value("Customer Team Member", {"user": doc.name, "is_removed": 0}, "customer")
	if customer:
		frappe.throw(
			_("{0} is on the team of {1}, a customer. Remove them from it before making them a Frappe consultant.").format(
				frappe.bold(doc.name), frappe.bold(customer)
			)
		)


def on_user_update(doc, method=None):
	"""User on_update. The work runs after commit: joining the Frappe team saves this User
	again, and doing that inside this save would leave the Desk form out of date."""
	if doc.name in ("Administrator", "Guest"):
		return
	if is_wanted(doc) != is_active(doc.name):
		frappe.enqueue(sync_consultant, user=doc.name, enqueue_after_commit=True)


def is_wanted(user_doc):
	return bool(user_doc.enabled) and CONSULTANT_ROLE in {row.role for row in user_doc.roles}


def is_active(user):
	return bool(frappe.db.get_value(CONSULTANT, user, "enabled"))


def sync_consultant(user):
	"""Bring the user's Frappe Consultant record in line with their role. Joining and leaving
	the team follow from the record (Frappe Consultant.after_insert / on_update)."""
	wanted = is_wanted(frappe.get_doc("User", user))
	if not frappe.db.exists(CONSULTANT, user):
		if wanted:
			frappe.get_doc({"doctype": CONSULTANT, "user": user}).insert(ignore_permissions=True)
		return
	doc = frappe.get_doc(CONSULTANT, user)
	if bool(doc.enabled) != wanted:
		doc.enabled = 1 if wanted else 0
		doc.save(ignore_permissions=True)


def frappe_partner():
	partner = frappe.db.get_single_value(SETTINGS, "implementation_partner")
	if not partner:
		frappe.throw(_("Set Implemented By in Starter Pack Settings before adding Frappe consultants."))
	return partner


def join_frappe_team(user):
	"""Make the consultant a member of the Frappe partner (not its admin), which gives them
	the partner side of Messaging."""
	partner = frappe_partner()
	member = frappe.db.get_value("Connect Partner Member", {"partner": partner, "user": user}, "name")
	if member:
		frappe.db.set_value("Connect Partner Member", member, {"is_removed": 0, "removed_on": None})
		frappe.get_doc("User", user).add_roles(PARTNER_ROLE)
		return
	frappe.get_doc(
		{"doctype": "Connect Partner Member", "partner": partner, "user": user, "is_admin": 0, "role": "Consultant"}
	).insert(ignore_permissions=True)


def leave_frappe_team(user):
	"""Hand the consultant's open orders on, then take them out of their threads and the
	Frappe team. Their orders, threads and messages stay for the record."""
	from connect.starter_packs.doctype.starter_pack_order.partner_rotation import assign_consultant

	for order in frappe.get_all(
		"Starter Pack Order",
		filters={"consultant": user, "status": ["in", OPEN_STATUSES]},
		order_by="creation asc",
		pluck="name",
	):
		assign_consultant(order, leaving=user)

	now = now_datetime()
	for row in frappe.get_all(
		"Connect Thread Member", filters={"user": user, "side": "Partner", "is_removed": 0}, pluck="name"
	):
		frappe.db.set_value("Connect Thread Member", row, {"is_removed": 1, "removed_on": now})
	member = frappe.db.get_value("Connect Partner Member", {"partner": frappe_partner(), "user": user}, "name")
	if member:
		frappe.db.set_value("Connect Partner Member", member, {"is_removed": 1, "removed_on": now})
	frappe.get_doc("User", user).remove_roles(PARTNER_ROLE)


def consultant_card(consultant):
	"""How a buyer sees their consultant: their name and photo, or the Frappe logo."""
	if not consultant:
		return None
	row = frappe.db.get_value(CONSULTANT, consultant, ["name", "full_name", "photo"], as_dict=True)
	if not row:
		return None
	partner = frappe.db.get_single_value(SETTINGS, "implementation_partner")
	logo = frappe.db.get_value("Partner", partner, "logo") if partner else None
	return {"name": row.name, "full_name": row.full_name, "photo": row.photo or logo, "label": row.full_name}
