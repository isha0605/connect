import frappe
from frappe import _
from frappe.utils import now_datetime

from connect.connect.permissions import _is_customer_admin, _is_partner_admin


def _post_system_message(thread, content):
	frappe.get_doc({
		"doctype": "Connect Message",
		"thread": thread,
		"sender": frappe.session.user,
		"message_type": "System",
		"content": content,
	}).insert(ignore_permissions=True)


def _my_company_membership(user):
	"""Returns (doctype, company, row) for whichever company this user belongs to, or
	(None, None, None) if neither. A user is assumed to belong to at most one company."""
	customer_row = frappe.db.get_value(
		"Connect Customer Member", {"user": user}, ["name", "customer", "is_admin"], as_dict=True
	)
	if customer_row:
		return "Connect Customer Member", customer_row.customer, customer_row
	partner_row = frappe.db.get_value(
		"Connect Partner Member", {"user": user}, ["name", "partner", "is_admin"], as_dict=True
	)
	if partner_row:
		return "Connect Partner Member", partner_row.partner, partner_row
	return None, None, None


@frappe.whitelist()
def add_thread_member(thread, email, side, permission="Write"):
	"""Add someone to a thread, creating their User account first if it doesn't exist yet.
	A regular portal admin has no create-permission on User, so this has to happen here,
	server-side, after independently re-checking the caller is really an admin of the
	side they're claiming to add to — never trust the client's own claim of authority."""
	email = email.strip().lower()
	user = frappe.session.user

	thread_doc = frappe.db.get_value("Connect Thread", thread, ["customer", "partner"], as_dict=True)
	if not thread_doc:
		frappe.throw(_("Thread not found"))

	if side == "Customer":
		authorized = _is_customer_admin(thread_doc.customer, user)
	elif side == "Partner":
		authorized = _is_partner_admin(thread_doc.partner, user)
	else:
		frappe.throw(_("Invalid side"))

	if not authorized:
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
		"thread": thread,
		"user": email,
		"side": side,
		"permission": permission,
		"added_by": user,
	})
	member.insert(ignore_permissions=True)

	_post_system_message(thread, _("{0} was added to this thread").format(email))

	return {"member": member.name, "created_user": created_user}


@frappe.whitelist()
def remove_thread_member(thread, member):
	"""Soft-remove a member from a thread. Only an admin of that member's own side may
	remove them — mirrors add_thread_member's authorization model."""
	user = frappe.session.user
	member_doc = frappe.get_doc("Connect Thread Member", member)
	if member_doc.thread != thread:
		frappe.throw(_("Member does not belong to this thread"))

	thread_doc = frappe.db.get_value("Connect Thread", thread, ["customer", "partner"], as_dict=True)
	if not thread_doc:
		frappe.throw(_("Thread not found"))

	if member_doc.side == "Customer":
		authorized = _is_customer_admin(thread_doc.customer, user)
	elif member_doc.side == "Partner":
		authorized = _is_partner_admin(thread_doc.partner, user)
	else:
		frappe.throw(_("Invalid side"))

	if not authorized:
		frappe.throw(_("Only an admin of your own side can remove members"), frappe.PermissionError)

	member_doc.is_removed = 1
	member_doc.save(ignore_permissions=True)

	_post_system_message(thread, _("{0} was removed from this thread").format(member_doc.user))

	return {"removed": member_doc.user}


@frappe.whitelist()
def close_thread(thread):
	"""Partner-admin-only, per spec — customer side has no close action."""
	user = frappe.session.user
	thread_doc = frappe.get_doc("Connect Thread", thread)

	if not _is_partner_admin(thread_doc.partner, user):
		frappe.throw(_("Only the partner admin can close this thread"), frappe.PermissionError)

	if thread_doc.status == "Closed":
		frappe.throw(_("Thread is already closed"))

	thread_doc.status = "Closed"
	thread_doc.closed_by = user
	thread_doc.closed_on = now_datetime()
	thread_doc.save(ignore_permissions=True)

	_post_system_message(thread, _("Thread closed by {0}").format(user))

	return {"status": thread_doc.status}


@frappe.whitelist()
def get_my_company_members():
	"""The caller's own company roster (Customer Member or Partner Member rows) — used to
	populate the 'transfer admin to' picker. Not thread-scoped, unlike everything else here."""
	user = frappe.session.user
	doctype, company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	fieldname = "customer" if doctype == "Connect Customer Member" else "partner"
	return frappe.get_all(doctype, filters={fieldname: company}, fields=["user", "is_admin"])


@frappe.whitelist()
def make_thread_admin(thread, member):
	"""Promote a thread member to company admin. Unlike a plain company-scoped transfer, the
	target here is a Connect Thread Member row, not necessarily an existing Connect Customer/
	Partner Member — most thread members (added via add_thread_member) never get a company
	membership row at all, so one is created for them here if missing."""
	user = frappe.session.user
	member_doc = frappe.get_doc("Connect Thread Member", member)
	if member_doc.thread != thread:
		frappe.throw(_("Member does not belong to this thread"))

	thread_doc = frappe.get_doc("Connect Thread", thread)

	if member_doc.side == "Customer":
		company_doctype, member_doctype, company, fieldname = (
			"Connect Customer", "Connect Customer Member", thread_doc.customer, "customer",
		)
		authorized = _is_customer_admin(company, user)
	elif member_doc.side == "Partner":
		company_doctype, member_doctype, company, fieldname = (
			"Connect Partner", "Connect Partner Member", thread_doc.partner, "partner",
		)
		authorized = _is_partner_admin(company, user)
	else:
		frappe.throw(_("Invalid side"))

	if not authorized:
		frappe.throw(_("Only an admin of your own side can do this"), frappe.PermissionError)

	my_row = frappe.db.get_value(member_doctype, {fieldname: company, "user": user}, "name")
	if my_row:
		frappe.db.set_value(member_doctype, my_row, "is_admin", 0)

	target_row = frappe.db.get_value(member_doctype, {fieldname: company, "user": member_doc.user}, "name")
	if target_row:
		frappe.db.set_value(member_doctype, target_row, "is_admin", 1)
	else:
		frappe.get_doc({
			"doctype": member_doctype,
			fieldname: company,
			"user": member_doc.user,
			"is_admin": 1,
		}).insert(ignore_permissions=True)

	frappe.db.set_value(company_doctype, company, "admin_user", member_doc.user)

	return {"new_admin": member_doc.user}


@frappe.whitelist()
def get_thread_admins(thread):
	"""Admin emails for the two companies on this thread — used to show an Admin badge
	next to the right member and to gate the per-member actions menu."""
	thread_doc = frappe.db.get_value("Connect Thread", thread, ["customer", "partner"], as_dict=True)
	if not thread_doc:
		frappe.throw(_("Thread not found"))

	partner_admin = frappe.db.get_value(
		"Connect Partner Member", {"partner": thread_doc.partner, "is_admin": 1}, "user"
	)
	customer_admin = frappe.db.get_value(
		"Connect Customer Member", {"customer": thread_doc.customer, "is_admin": 1}, "user"
	)
	return {"partner_admin": partner_admin, "customer_admin": customer_admin}


@frappe.whitelist()
def get_my_context():
	user = frappe.session.user
	customer_membership = frappe.db.get_value(
		"Connect Customer Member", {"user": user}, ["customer", "is_admin"], as_dict=True
	)
	partner_membership = frappe.db.get_value(
		"Connect Partner Member", {"user": user}, ["partner", "is_admin"], as_dict=True
	)
	return {
		"user": user,
		"customer": customer_membership,
		"partner": partner_membership,
	}
