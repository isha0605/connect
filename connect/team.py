import frappe
from frappe import _
from frappe.utils import validate_email_address

from connect.permissions import _is_customer_admin, _is_partner_admin, _my_company_membership


def get_my_company_members():
	"""Returns the caller's own company roster, used to populate the "transfer admin to" picker."""
	user = frappe.session.user
	doctype, company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	fieldname = "customer" if doctype == "Customer Team Member" else "partner"
	return frappe.get_all(doctype, filters={fieldname: company}, fields=["user", "is_admin"])


def get_my_team():
	"""Returns the caller's own company roster with names and photos, to render the Settings Users list."""
	user = frappe.session.user
	doctype, company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	fieldname = "customer" if doctype == "Customer Team Member" else "partner"
	role_field = "designation" if doctype == "Customer Team Member" else "role"

	Member = frappe.qb.DocType(doctype)
	UserTable = frappe.qb.DocType("User")
	return (
		frappe.qb.from_(Member)
		.left_join(UserTable)
		.on(Member.user == UserTable.name)
		.select(
			Member.name, Member.user, Member.is_admin, Member.is_removed,
			Member[role_field].as_("role"), UserTable.full_name, UserTable.user_image,
		)
		.where(Member[fieldname] == company)
		.orderby(Member.is_admin, order=frappe.qb.desc)
		.orderby(Member.creation, order=frappe.qb.asc)
		.run(as_dict=True)
	)


def remove_team_member(member):
	"""Removes someone from the caller's own company roster, on whichever side the caller belongs to."""
	user = frappe.session.user
	doctype, _company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	doc = frappe.get_doc(doctype, member)
	doc.remove(user)
	return {"removed": doc.user}


def add_team_member(email, role=None, password=None):
	"""Invites someone onto the caller's own company roster, creating their user account first if it doesn't exist."""
	user = frappe.session.user
	doctype, company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	is_customer_side = doctype == "Customer Team Member"
	authorized = (
		_is_customer_admin(company, user) if is_customer_side else _is_partner_admin(company, user)
	)
	if not authorized:
		frappe.throw(_("Only an admin can add a team member"), frappe.PermissionError)

	email = (email or "").strip().lower()
	if not email:
		frappe.throw(_("Enter an email address"))
	if not validate_email_address(email, throw=False):
		frappe.throw(_("Enter a valid email address"))

	fieldname = "customer" if is_customer_side else "partner"
	if frappe.db.exists(doctype, {fieldname: company, "user": email}):
		frappe.throw(_("{0} is already a member").format(email))

	created_user = False
	if not frappe.db.exists("User", email):
		new_user = frappe.new_doc("User")
		new_user.email = email
		new_user.first_name = email.split("@")[0]
		new_user.user_type = "Website User"
		new_user.send_welcome_email = 0
		if password:
			new_user.new_password = password
		new_user.insert(ignore_permissions=True)
		created_user = True

	role_field = "designation" if is_customer_side else "role"
	member_doc = frappe.get_doc({
		"doctype": doctype,
		fieldname: company,
		"user": email,
		"is_admin": 0,
		role_field: role,
	})
	member_doc.insert(ignore_permissions=True)

	return {"member": member_doc.name, "created_user": created_user}
