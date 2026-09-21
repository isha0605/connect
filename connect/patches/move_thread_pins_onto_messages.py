# Copyright (c) 2026
# For license information, please see license.txt

import frappe

# (message doctype, thread doctype) for company threads and DMs.
CONVERSATIONS = [("Connect Message", "Connect Thread"), ("Connect DM Message", "Connect DM Thread")]


def execute():
	"""Moves pins from a single `pinned_message` link on the thread onto the pinned messages themselves, so
	a conversation can hold any number of pins.

	Runs before the doctypes are migrated, because dropping `pinned_message` from the doctype JSON would
	otherwise let the schema sync remove the column before its data has been read. The new columns are
	therefore added here first, in the exact shape Frappe would create them, so the later schema sync finds
	them already in place. Safe to re-run.
	"""
	for message_doctype, thread_doctype in CONVERSATIONS:
		if not (frappe.db.table_exists(message_doctype) and frappe.db.table_exists(thread_doctype)):
			continue

		_add_pin_columns(message_doctype)

		if frappe.db.has_column(thread_doctype, "pinned_message"):
			pins = frappe.db.sql(
				f"select pinned_message, modified_by, modified from `tab{thread_doctype}` "
				"where pinned_message is not null and pinned_message != ''",
				as_dict=True,
			)
			for pin in pins:
				frappe.db.set_value(
					message_doctype,
					pin.pinned_message,
					{"is_pinned": 1, "pinned_by": pin.modified_by, "pinned_at": pin.modified},
					update_modified=False,
				)
			frappe.db.sql_ddl(f"alter table `tab{thread_doctype}` drop column `pinned_message`")


def _add_pin_columns(doctype):
	columns = {
		"is_pinned": "int(1) not null default 0",
		"pinned_by": "varchar(140)",
		"pinned_at": "datetime(6)",
	}
	for column, definition in columns.items():
		if not frappe.db.has_column(doctype, column):
			frappe.db.sql_ddl(f"alter table `tab{doctype}` add column `{column}` {definition}")
