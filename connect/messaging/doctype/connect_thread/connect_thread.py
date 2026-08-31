# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class ConnectThread(Document):
	def validate(self):
		if not self.is_new():
			# customer/partner define which two companies' history lives in this thread —
			# the doctype otherwise grants "write" to any partner admin (so they can close
			# it), and without this, that same write access could reassign the thread to an
			# unrelated customer, silently handing them another company's message history
			# the next time that customer messages this partner.
			prev = frappe.db.get_value("Connect Thread", self.name, ["customer", "partner"], as_dict=True)
			if prev and (prev.customer != self.customer or prev.partner != self.partner):
				frappe.throw(_("A thread's customer and partner can't be changed after it's created"))

		existing = frappe.db.exists(
			"Connect Thread",
			{"customer": self.customer, "partner": self.partner, "name": ["!=", self.name]},
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

	def pin(self, message, user):
		"""Pins a message to the top of the thread, replacing whichever was pinned before."""
		from connect.notifications import notify_thread_pin_changed
		from connect.permissions import _check_can_write

		_check_can_write(self.name, user)
		message_doc = frappe.get_doc("Connect Message", message)
		self.pinned_message = message_doc.name
		self.save(ignore_permissions=True)
		notify_thread_pin_changed(self, message_doc, user)

	def unpin(self, user):
		from connect.notifications import notify_thread_pin_changed
		from connect.permissions import _check_can_write

		_check_can_write(self.name, user)
		self.pinned_message = None
		self.save(ignore_permissions=True)
		notify_thread_pin_changed(self, None, user)

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

		member = frappe.get_doc({
			"doctype": "Connect Thread Member",
			"thread": self.name,
			"user": email,
			"side": side,
			"permission": permission,
			"added_by": added_by,
		})
		member.insert(ignore_permissions=True)

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
		member_doc.save(ignore_permissions=True)

		self.post_system_message(_("{0} was removed from this thread").format(member_doc.user))

		return member_doc

	def close(self, user):
		"""Partner-admin-only, per spec — customer side has no close action."""
		from connect.permissions import _is_partner_admin

		if not _is_partner_admin(self.partner, user):
			frappe.throw(_("Only the partner admin can close this thread"), frappe.PermissionError)
		if self.status == "Closed":
			frappe.throw(_("Thread is already closed"))

		self.status = "Closed"
		self.closed_by = user
		self.closed_on = now_datetime()
		self.save(ignore_permissions=True)

		self.post_system_message(_("Thread closed by {0}").format(user))
