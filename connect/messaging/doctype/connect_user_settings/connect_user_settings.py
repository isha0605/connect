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
	"""The caller's own working hours and after-hours behavior — the defaults if they've never saved any."""
	user = frappe.session.user
	doc = frappe.get_doc("Connect User Settings", user) if frappe.db.exists("Connect User Settings", user) else None
	return _as_dict(doc or frappe.new_doc("Connect User Settings"))


def update_my_settings(work_start, work_end, work_days, after_hours_behavior):
	"""Saves the caller's own settings. Always acts on the session user: this doctype is only reachable
	through here, so nobody can read or change someone else's."""
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
