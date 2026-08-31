# Copyright (c) 2026
# For license information, please see license.txt

import frappe

from connect.notifications import _set_thread_last_message


def _backfill(thread_doctype, message_doctype, thread_field):
	if not frappe.db.table_exists(thread_doctype) or not frappe.db.table_exists(message_doctype):
		return

	for name in frappe.get_all(thread_doctype, pluck="name"):
		rows = frappe.get_all(
			message_doctype,
			filters={thread_field: name},
			fields=["name", "creation", "sender", "message_type", "content", "file_name"],
			order_by="creation desc",
			limit_page_length=1,
		)
		if rows:
			_set_thread_last_message(thread_doctype, name, rows[0])


def execute():
	"""Backfills the new last_message* denormalized fields (see connect.notifications) on every
	existing Connect Thread/Connect DM Thread from their real latest message. Without this,
	threads created before this patch would show a blank sidebar preview and sort as if they had
	no activity until their next message arrives.
	"""
	_backfill("Connect Thread", "Connect Message", "thread")
	_backfill("Connect DM Thread", "Connect DM Message", "dm_thread")
