# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Count
from frappe.utils import get_fullname, now_datetime

from connect.membership import OWNER


class ConnectThreadMember(Document):
	def validate(self):
		if frappe.db.exists(
			"Connect Thread Member",
			{"thread": self.thread, "user": self.user, "is_removed": 0, "name": ["!=", self.name]},
		):
			frappe.throw(_("{0} is already an active member of this thread").format(self.user))

		if not self.added_on:
			self.added_on = now_datetime()

		if self.is_removed and not self.removed_on:
			self.removed_on = now_datetime()
		if not self.is_removed:
			self.removed_on = None

	def make_admin(self, user):
		"""Transfers admin from the caller to this member, creating their company row if they don't yet have one."""
		if self.is_removed:
			frappe.throw(_("A removed member can't be made admin"))

		thread_doc = frappe.get_doc("Connect Thread", self.thread)
		if self.side == "Partner":
			member = self._company_row("Connect Partner Member", {"partner": thread_doc.partner})
		elif self.side == "Customer":
			values = {"customer": thread_doc.customer, "full_name": get_fullname(self.user)}
			member = self._company_row("Customer Team Member", values)
		else:
			frappe.throw(_("Invalid side"))

		# Checked before a new company row is saved, so a refused hand-over leaves nothing behind.
		if member.get_access_of(user) != OWNER:
			frappe.throw(_("Only the Owner can hand over the company"), frappe.PermissionError)
		if member.is_new():
			member.insert(ignore_permissions=True)
		member.set_access_level(OWNER, user)

	def _company_row(self, doctype: str, values: dict):
		"""This member's row on the company's team, or a new unsaved one when they have none."""
		company_field = next(iter(values))
		row = frappe.db.get_value(doctype, {company_field: values[company_field], "user": self.user})
		if row:
			return frappe.get_doc(doctype, row)
		return frappe.get_doc({"doctype": doctype, "user": self.user, **values})


def get_unread_counts(threads: list[str], user: str) -> dict[str, int]:
	"""Counts messages from others since the user last read each thread, in one query.

	A removed member's count stops at removal, matching the frozen view they keep.
	"""
	memberships = _get_memberships_by_thread(threads, user)
	message = frappe.qb.DocType("Connect Message")

	unread_window = None
	for thread in threads:
		condition = message.thread == thread
		membership = memberships.get(thread)
		if membership and membership.last_read_at:
			condition &= message.creation > membership.last_read_at
		if membership and membership.is_removed and membership.removed_on:
			condition &= message.creation <= membership.removed_on
		unread_window = condition if unread_window is None else unread_window | condition

	counts = (
		frappe.qb.from_(message)
		.select(message.thread, Count("*"))
		.where(message.sender != user)
		.where(unread_window)
		.groupby(message.thread)
	).run()
	return dict(counts)



def mark_read(thread: str, user: str) -> None:
	"""Clears the user's unread badge; does nothing if they are no longer an active member."""
	frappe.db.set_value(
		"Connect Thread Member",
		{"thread": thread, "user": user, "is_removed": 0},
		"last_read_at",
		now_datetime(),
	)

def _get_memberships_by_thread(threads: list[str], user: str) -> dict:
	rows = frappe.get_all(
		"Connect Thread Member",
		filters={"thread": ["in", threads], "user": user},
		fields=["thread", "last_read_at", "is_removed", "removed_on"],
		# a re-added user also has their old removed row; sorting it first lets the active row win
		order_by="is_removed desc",
	)
	return {row.thread: row for row in rows}
