# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_datetime

# The changes Frappe's Version history records that the Activity tab shows, by DocType.
TRACKED_FIELDS = {
	"Project Quote": {"lead_stage": "Stage", "lead_owner": "Assigned to", "probability": "Probability"},
	"Partner Customer": {"stage": "Stage", "assigned_to": "Assigned to"},
}
USER_FIELDS = ("lead_owner", "assigned_to")


def notes_of(partner: str, customer: str) -> list[dict]:
	"""The partner team's notes on the customer, newest first. Callers check access first."""
	rows = frappe.get_all(
		"Partner Note",
		filters={"partner": partner, "customer": customer},
		fields=["name", "content", "owner", "creation"],
		order_by="creation desc",
	)
	names = _user_names({row.owner for row in rows})
	return [
		{"id": row.name, "text": row.content, "by": row.owner, "by_name": names.get(row.owner), "at": row.creation}
		for row in rows
	]


def add_note(partner: str, customer: str, content: str, quote: str | None = None) -> None:
	content = (content or "").strip()
	if not content:
		frappe.throw(_("Write a note first."))
	# Only the partner's team works with these records; callers have checked the user is on it.
	frappe.get_doc(
		{"doctype": "Partner Note", "partner": partner, "customer": customer, "content": content, "quote": quote}
	).insert(ignore_permissions=True)


def follow_ups_of(partner: str, customer: str) -> list[dict]:
	rows = frappe.get_all(
		"Partner Follow Up",
		filters={"partner": partner, "customer": customer},
		fields=["name", "followed_up_on", "mode", "spoke_to", "notes", "owner", "quote"],
		order_by="followed_up_on desc",
	)
	names = _user_names({row.owner for row in rows})
	return [
		{
			"id": row.name,
			"at": row.followed_up_on,
			"mode": row.mode,
			"spoke_to": row.spoke_to,
			"notes": row.notes,
			"by": row.owner,
			"by_name": names.get(row.owner),
			"quote": row.quote,
		}
		for row in rows
	]


def log_follow_up(partner: str, customer: str, values: dict, quote: str | None = None) -> None:
	"""Logs a follow-up from the dialog: when, how (Call, Demo, Email, Meeting), who picked up, notes."""
	values = frappe._dict(values or {})
	frappe.get_doc(
		{
			"doctype": "Partner Follow Up",
			"partner": partner,
			"customer": customer,
			"followed_up_on": get_datetime(values.followed_up_on),
			"mode": values.mode,
			"spoke_to": (values.spoke_to or "").strip(),
			"notes": (values.notes or "").strip(),
			"quote": quote,
		}
	).insert(ignore_permissions=True)


def activity_of(records: dict[str, list[str]], briefs: list[dict], follow_ups: list[dict]) -> list[dict]:
	"""The Activity tab, oldest first: each brief arriving, the changes Frappe recorded on the
	`records` ({DocType: [names]}), and the follow-ups logged."""
	entries = [
		{
			"id": f"brief-{brief['name']}",
			"at": brief["at"],
			"by": brief["by"],
			"kind": "created",
			# On a customer's page there are several briefs, so each says which.
			"text": _("sent the brief “{0}”").format(brief["project_name"]) if brief.get("project_name") else _("sent this brief"),
		}
		for brief in briefs
	]
	for doctype, names in records.items():
		entries += _changes(doctype, names)
	entries += [
		{
			"id": f"follow-up-{row['id']}",
			"at": row["at"],
			"by": row["by_name"] or row["by"],
			"kind": "note",
			"text": _follow_up_text(row),
		}
		for row in follow_ups
	]
	return sorted(entries, key=lambda entry: get_datetime(entry["at"]))


def _changes(doctype: str, names: list[str]) -> list[dict]:
	if not names:
		return []
	tracked = TRACKED_FIELDS[doctype]
	# Version is Frappe's change history; read without permission checks for records the
	# caller has already been checked for.
	versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": doctype, "docname": ["in", names]},
		fields=["name", "owner", "creation", "data"],
		order_by="creation asc",
	)
	changes = [
		(version, field, before, after)
		for version in versions
		for field, before, after in (frappe.parse_json(version.data) or {}).get("changed", [])
		if field in tracked
	]
	users = set()
	for version, field, before, after in changes:
		users.add(version.owner)
		if field in USER_FIELDS:
			users.update((before, after))
	names_by_user = _user_names(users)
	return [entry for change in changes for entry in _change_entries(change, tracked, names_by_user)]


def _change_entries(change, tracked: dict, names: dict) -> list[dict]:
	version, field, before, after = change
	shown = (lambda value: names.get(value) or value) if field in USER_FIELDS else (lambda value: value)
	by = names.get(version.owner) or version.owner
	entry = {
		"id": f"{version.name}-{field}",
		"at": version.creation,
		"by": by,
		"kind": "change",
		"field": tracked[field],
		"from": shown(before) or _("Not set"),
		"to": shown(after) or _("Not set"),
	}
	if field == "lead_stage" and after == "Won":
		return [entry, {**entry, "id": f"{version.name}-converted", "kind": "note", "text": _("converted the lead to a deal")}]
	return [entry]


def _follow_up_text(row: dict) -> str:
	mode = (row["mode"] or "").lower()
	if row["spoke_to"]:
		return _("logged a {0} with {1}").format(mode, row["spoke_to"])
	return _("logged a {0}").format(mode)


def _user_names(users: set[str]) -> dict:
	users = {user for user in users if user}
	if not users:
		return {}
	return dict(frappe.get_all("User", filters={"name": ["in", list(users)]}, fields=["name", "full_name"], as_list=True))
