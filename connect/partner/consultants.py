# Copyright (c) 2026
# For license information, please see license.txt

"""Frappe consultants: the Frappe staff who deliver Starter Packs.

A System Manager gives a User the Frappe Consultant role, and that's all it takes. The
consultant gets a Partner of their own (Frappe Consultant ticked, the Frappe logo) with
them as its admin, so:

- the Starter Pack round robin hands them orders (partner_rotation only draws from
  consultants);
- each consultant has their own thread with a buyer, and Messaging shows them the partner
  side of it, CRM settings included, with no change to Messaging;
- they never appear anywhere a buyer browses partners (see is_listed_partner).

Taking the role away (or disabling the User) switches their Partner off, hands their open
orders to the next consultant, and takes them out of those threads. The Partner and its
history stay. Giving the role back switches it on again.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from connect.roles import CONSULTANT_ROLE, PARTNER_ROLE

FRAPPE_LOGO = "/assets/connect/images/frappe-logo.png"
SETTINGS = "Starter Pack Settings"
# Orders still being delivered: the ones a leaving consultant hands over.
OPEN_STATUSES = ["New", "Partner Assigned", "In Progress"]


def on_user_update(doc, method=None):
	"""User on_update. The work runs after commit: making someone a partner member saves their
	User again, and doing that inside this save would leave the Desk form out of date."""
	if doc.name in ("Administrator", "Guest"):
		return
	if is_wanted(doc) != is_active(doc.name):
		frappe.enqueue(sync_consultant, user=doc.name, enqueue_after_commit=True)


def is_wanted(user_doc):
	return bool(user_doc.enabled) and CONSULTANT_ROLE in {row.role for row in user_doc.roles}


def is_active(user):
	partner = get_consultant_partner(user)
	return bool(partner and frappe.db.get_value("Partner", partner, "enabled"))


def sync_consultant(user):
	"""Bring the user's consultant Partner in line with their role."""
	user_doc = frappe.get_doc("User", user)
	if is_wanted(user_doc):
		start_consultant(user_doc)
	else:
		partner = get_consultant_partner(user)
		if partner:
			stop_consultant(user, partner)


def get_consultant_partner(user):
	"""The user's own consultant Partner, or None."""
	partners = frappe.get_all("Connect Partner Member", filters={"user": user}, pluck="partner")
	if not partners:
		return None
	found = frappe.get_all(
		"Partner", filters={"name": ["in", partners], "is_frappe_consultant": 1}, pluck="name", limit=1
	)
	return found[0] if found else None


def start_consultant(user_doc):
	partner = get_consultant_partner(user_doc.name)
	if partner:
		# Back again: switch their Partner on (saved, so they get a place in the rotation) and
		# give them Messaging again.
		doc = frappe.get_doc("Partner", partner)
		doc.update({"enabled": 1, "starter_pack": 1})
		doc.save(ignore_permissions=True)
		frappe.db.set_value(
			"Connect Partner Member",
			{"partner": partner, "user": user_doc.name},
			{"is_removed": 0, "removed_on": None},
		)
		frappe.get_doc("User", user_doc.name).add_roles(PARTNER_ROLE)
		return partner

	frappe_partner = frappe.db.get_single_value(SETTINGS, "implementation_partner")
	logo, country = (
		frappe.db.get_value("Partner", frappe_partner, ["logo", "country"]) if frappe_partner else (None, None)
	)
	partner = frappe.get_doc(
		{
			"doctype": "Partner",
			"partner_name": consultant_partner_name(user_doc),
			"tier": "Gold",
			"country": country or "India",
			"logo": logo or FRAPPE_LOGO,
			"enabled": 1,
			"is_featured": 0,
			"starter_pack": 1,
			"is_frappe_consultant": 1,
			"verification_status": "Verified",
		}
	).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Connect Partner Member",
			"partner": partner.name,
			"user": user_doc.name,
			"is_admin": 1,
			"role": "Consultant",
		}
	).insert(ignore_permissions=True)
	return partner.name


def consultant_partner_name(user_doc):
	"""What buyers see in their inbox and on the setup page: "Priya Shah · Frappe". Partners are
	named by partner_name, so a clash (two consultants with one name) gets their email added."""
	name = _("{0} · Frappe").format(user_doc.full_name or user_doc.name)
	if frappe.db.exists("Partner", name):
		name = _("{0} · Frappe ({1})").format(user_doc.full_name or user_doc.name, user_doc.name)
	return name


def stop_consultant(user, partner):
	"""Switch the consultant off: no new orders, their open orders to whoever is next, and
	out of Messaging. Their Partner, orders and messages stay for the record."""
	from connect.customer.doctype.starter_pack_order.implementation import reassign

	frappe.db.set_value("Partner", partner, "enabled", 0)
	for order in frappe.get_all(
		"Starter Pack Order",
		filters={"partner": partner, "status": ["in", OPEN_STATUSES]},
		order_by="creation asc",
		pluck="name",
	):
		reassign(order)

	now = now_datetime()
	frappe.db.set_value(
		"Connect Partner Member", {"partner": partner, "user": user}, {"is_removed": 1, "removed_on": now}
	)
	for row in frappe.get_all(
		"Connect Thread Member", filters={"user": user, "side": "Partner", "is_removed": 0}, pluck="name"
	):
		frappe.db.set_value("Connect Thread Member", row, {"is_removed": 1, "removed_on": now})
	frappe.get_doc("User", user).remove_roles(PARTNER_ROLE)


def is_listed_partner(partner):
	"""False for a consultant: buyers never browse to one, only reach them through an order."""
	return not frappe.db.get_value("Partner", partner, "is_frappe_consultant")


def check_listed(partner):
	"""Answer as if a consultant didn't exist, except to the consultant and to admins."""
	if is_listed_partner(partner):
		return
	user = frappe.session.user
	if "System Manager" in frappe.get_roles(user) or frappe.db.exists(
		"Connect Partner Member", {"partner": partner, "user": user}
	):
		return
	frappe.throw(_("Partner not found"), frappe.DoesNotExistError)
