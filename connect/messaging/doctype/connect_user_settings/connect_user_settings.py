# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_time

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
AFTER_HOURS_BEHAVIORS = ("Do nothing", "Suggest sending silently", "Always send silently")


class ConnectUserSettings(Document):
	def validate(self):
		if get_time(self.work_start) >= get_time(self.work_end):
			frappe.throw(_("Your work day must end after it starts"))
		if not any(self.get(day) for day in WEEKDAYS):
			frappe.throw(_("Pick at least one working day"))


def _hhmm(value):
	return get_time(value).strftime("%H:%M")


def _as_dict(doc):
	return {
		"work_start": _hhmm(doc.work_start),
		"work_end": _hhmm(doc.work_end),
		"work_days": [day for day in WEEKDAYS if doc.get(day)],
		"after_hours_behavior": doc.after_hours_behavior,
	}


def get_my_settings():
	"""Returns the caller's working hours, falling back to defaults so a first-time user still sees sensible values."""
	user = frappe.session.user
	doc = frappe.get_doc("Connect User Settings", user) if frappe.db.exists("Connect User Settings", user) else None
	return _as_dict(doc or frappe.new_doc("Connect User Settings"))


def get_settings_for_users(users):
	"""Batches working-hours lookup for several users so a thread's partner-side quiet-hour check is one query, not N."""
	users = list(dict.fromkeys(users))  # de-dup, keep order
	docs = {
		d.name: d
		for d in frappe.get_all(
			"Connect User Settings",
			filters={"name": ["in", users]},
			fields=["name", "work_start", "work_end", *WEEKDAYS, "after_hours_behavior"],
		)
	}
	return {user: _as_dict(docs.get(user) or frappe.new_doc("Connect User Settings")) for user in users}


def update_my_settings(work_start, work_end, work_days, after_hours_behavior):
	"""Saves the caller's own settings, keyed to the session user so nobody can change someone else's."""
	user = frappe.session.user
	work_days = frappe.parse_json(work_days) if isinstance(work_days, str) else work_days
	if after_hours_behavior not in AFTER_HOURS_BEHAVIORS:
		frappe.throw(_("Unknown after-hours behavior"))

	if frappe.db.exists("Connect User Settings", user):
		doc = frappe.get_doc("Connect User Settings", user)
	else:
		doc = frappe.new_doc("Connect User Settings")
		doc.user = user

	doc.work_start = work_start
	doc.work_end = work_end
	for day in WEEKDAYS:
		doc.set(day, 1 if day in (work_days or []) else 0)
	doc.after_hours_behavior = after_hours_behavior
	doc.save(ignore_permissions=True)
	return _as_dict(doc)


def get_partner_hours_for_thread(thread=None, dm_thread=None):
	"""Working hours for the partner side of one conversation — the customer-facing "are they
	around right now" signal, as opposed to Connect User Settings' get_my_settings (everyone's own
	personal hours). A company thread can have several partner team members; a DM has exactly one,
	and only if the other party happens to be a partner at all. Empty `members` means there's
	nothing to show: no partner on the thread yet, or (for a DM) the other person isn't a partner.
	"""
	partner_name = None
	partner_users = []

	if thread:
		members = frappe.get_all(
			"Connect Thread Member",
			filters={"thread": thread, "side": "Partner", "is_removed": 0},
			fields=["user"],
		)
		partner_users = [m.user for m in members]
		partner = frappe.db.get_value("Connect Thread", thread, "partner")
		if partner:
			partner_name = frappe.db.get_value("Partner", partner, "partner_name")
	elif dm_thread:
		user_a, user_b = frappe.db.get_value("Connect DM Thread", dm_thread, ["user_a", "user_b"])
		other = user_b if user_a == frappe.session.user else user_a
		partner = frappe.db.get_value("Connect Partner Member", {"user": other}, "partner")
		if partner:
			partner_users = [other]
			partner_name = frappe.db.get_value("Partner", partner, "partner_name")

	if not partner_users:
		return {"partner_name": None, "members": []}

	settings = get_settings_for_users(partner_users)
	return {
		"partner_name": partner_name,
		"members": [
			{"work_start": s["work_start"], "work_end": s["work_end"], "work_days": s["work_days"]}
			for s in settings.values()
		],
	}
