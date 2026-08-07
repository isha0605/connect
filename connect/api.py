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
def transfer_admin(new_admin_email):
	"""Only the CURRENT admin can transfer their own admin rights — this is not something
	a regular member or an outsider can trigger for someone else."""
	user = frappe.session.user
	doctype, company, my_row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))
	if not my_row.is_admin:
		frappe.throw(_("Only the current admin can transfer admin rights"), frappe.PermissionError)

	fieldname = "customer" if doctype == "Connect Customer Member" else "partner"
	new_admin_row = frappe.db.get_value(doctype, {fieldname: company, "user": new_admin_email}, "name")
	if not new_admin_row:
		frappe.throw(_("{0} is not a member of your company").format(new_admin_email))

	frappe.db.set_value(doctype, my_row.name, "is_admin", 0)
	frappe.db.set_value(doctype, new_admin_row, "is_admin", 1)

	company_doctype = "Connect Customer" if doctype == "Connect Customer Member" else "Connect Partner"
	frappe.db.set_value(company_doctype, company, "admin_user", new_admin_email)

	return {"new_admin": new_admin_email}


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
