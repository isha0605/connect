# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from connect.permissions import _get_partner_admin


class ConnectThread(Document):
	def validate(self):
		if not self.is_new():
			# freezing customer/partner stops a partner admin's write access from silently reassigning the thread to another customer
			prev = frappe.db.get_value("Connect Thread", self.name, ["customer", "partner"], as_dict=True)
			if prev and (prev.customer != self.customer or prev.partner != self.partner):
				frappe.throw(_("A thread's customer and partner can't be changed after it's created"))

		# One thread per customer and partner, or with Frappe, one per Starter Pack consultant
		# (see connect.partner.consultants). The consultant may change: an order handed to
		# another consultant takes its thread along.
		existing = frappe.db.exists(
			"Connect Thread",
			{
				"customer": self.customer,
				"partner": self.partner,
				"consultant": self.consultant or ["is", "not set"],
				"name": ["!=", self.name],
			},
		)
		if existing:
			frappe.throw(
				_("A thread between {0} and {1} already exists: {2}").format(
					self.customer, self.partner, existing
				)
			)

		if self.status == "Closed" and not self.closed_on:
			self.closed_on = now_datetime()
		if self.status == "Open":
			self.closed_by = None
			self.closed_on = None

	def post_system_message(self, content):
		frappe.get_doc({
			"doctype": "Connect Message",
			"thread": self.name,
			"sender": frappe.session.user,
			"message_type": "System",
			"content": content,
		}).insert(ignore_permissions=True)

	def _authorize_side_admin(self, side, user):
		from connect.permissions import _is_customer_admin, _is_partner_admin

		if side == "Customer":
			return _is_customer_admin(self.customer, user)
		if side == "Partner":
			return _is_partner_admin(self.partner, user)
		frappe.throw(_("Invalid side"))

	def add_member(self, email, side, permission, added_by):
		"""Adds someone to this thread, creating their user account first if it doesn't exist yet."""
		email = email.strip().lower()
		if not self._authorize_side_admin(side, added_by):
			frappe.throw(_("Only an admin of your own side can add members"), frappe.PermissionError)

		created_user = False
		if not frappe.db.exists("User", email):
			frappe.get_doc({
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"user_type": "Website User",
				"send_welcome_email": 0,
			}).insert(ignore_permissions=True)
			created_user = True

		# caller was verified as same-side admin above, which satisfies has_thread_member_permission's create rule
		member = frappe.get_doc({
			"doctype": "Connect Thread Member",
			"thread": self.name,
			"user": email,
			"side": side,
			"permission": permission,
			"added_by": added_by,
		})
		member.insert()

		self.post_system_message(_("{0} was added to this thread").format(email))

		return member, created_user

	def remove_member(self, member_name, removed_by):
		"""Soft-removes a member from this thread; only an admin of their own side may do this."""
		member_doc = frappe.get_doc("Connect Thread Member", member_name)
		if member_doc.thread != self.name:
			frappe.throw(_("Member does not belong to this thread"))

		if not self._authorize_side_admin(member_doc.side, removed_by):
			frappe.throw(_("Only an admin of your own side can remove members"), frappe.PermissionError)

		member_doc.is_removed = 1
		member_doc.save()

		self.post_system_message(_("{0} was removed from this thread").format(member_doc.user))

		return member_doc

	def close(self, user):
		"""Closes the thread, restricted to a partner admin since the customer side has no close action by spec."""
		from connect.permissions import _is_partner_admin

		if not _is_partner_admin(self.partner, user):
			frappe.throw(_("Only the partner admin can close this thread"), frappe.PermissionError)
		if self.status == "Closed":
			frappe.throw(_("Thread is already closed"))

		self.status = "Closed"
		self.closed_by = user
		self.closed_on = now_datetime()
		self.save()

		self.post_system_message(_("Thread closed by {0}").format(user))


def open_contact_thread(customer: str, partner: str, user: str) -> str:
	"""The customer's Contact Partner thread with the partner, created if missing, with the
	user and the partner's admin as members."""
	# Not a Starter Pack consultant's thread with Frappe: those come from the order.
	thread = frappe.db.get_value(
		"Connect Thread", {"customer": customer, "partner": partner, "consultant": ["is", "not set"]}, "name"
	)
	if not thread:
		thread = frappe.get_doc({
			"doctype": "Connect Thread",
			"customer": customer,
			"partner": partner,
		}).insert().name

	ensure_thread_member(thread, user, "Customer", user)

	partner_admin = _get_partner_admin(partner)
	if partner_admin:
		ensure_thread_member(thread, partner_admin, "Partner", user)
	return thread


def get_or_open_thread(customer: str, partner: str, user: str, consultant: str | None = None) -> str:
	"""The customer's thread with the partner — with Frappe, the one with this consultant —
	reopened if it was closed. Its members are the buyer and, on the partner side, the
	consultant, or the partner's admin when there's no consultant (the thread Contact Partner
	opens)."""
	key = {"customer": customer, "partner": partner, "consultant": consultant or ["is", "not set"]}
	thread = frappe.db.get_value("Connect Thread", key, "name")
	if thread:
		if frappe.db.get_value("Connect Thread", thread, "status") == "Closed":
			doc = frappe.get_doc("Connect Thread", thread)
			doc.status = "Open"
			doc.save(ignore_permissions=True)
	else:
		thread = (
			frappe.get_doc(
				{"doctype": "Connect Thread", "customer": customer, "partner": partner, "consultant": consultant}
			)
			.insert(ignore_permissions=True)
			.name
		)

	ensure_thread_member(thread, user, "Customer", user)
	partner_side = consultant or _get_partner_admin(partner)
	if partner_side:
		ensure_partner_member(thread, partner_side, user)
	return thread


def ensure_thread_member(thread: str, user: str, side: str, added_by: str) -> None:
	"""Idempotent: only creates a membership row if this user doesn't already have one."""
	if not frappe.db.exists("Connect Thread Member", {"thread": thread, "user": user}):
		frappe.get_doc({
			"doctype": "Connect Thread Member",
			"thread": thread,
			"user": user,
			"side": side,
			"permission": "Write",
			"added_by": added_by,
		}).insert(ignore_permissions=True)


def ensure_partner_member(thread: str, member: str, added_by: str) -> None:
	"""Add someone to a thread's partner side, or bring them back if they'd been removed."""
	row = frappe.db.get_value("Connect Thread Member", {"thread": thread, "user": member}, ["name", "is_removed"], as_dict=True)
	if not row:
		ensure_thread_member(thread, member, "Partner", added_by)
	elif row.is_removed:
		frappe.db.set_value("Connect Thread Member", row.name, {"is_removed": 0, "removed_on": None})


def remove_partner_member(thread: str, member: str) -> None:
	row = frappe.db.get_value("Connect Thread Member", {"thread": thread, "user": member, "is_removed": 0}, "name")
	if row:
		frappe.db.set_value("Connect Thread Member", row, {"is_removed": 1, "removed_on": now_datetime()})
