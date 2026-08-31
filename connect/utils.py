import os

import frappe
from frappe import _
from frappe.utils import cint, validate_email_address

from connect.customer.doctype.customer.customer import get_customer_for_user
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


def get_my_profile():
	"""Returns the caller's own name, photo, and contact details for the sidebar avatar and Settings Profile section."""
	user = frappe.session.user
	UserTable = frappe.qb.DocType("User")
	PartnerMember = frappe.qb.DocType("Connect Partner Member")
	rows = (
		frappe.qb.from_(UserTable)
		.left_join(PartnerMember)
		.on(PartnerMember.user == UserTable.name)
		.select(UserTable.full_name, UserTable.user_image, UserTable.phone, PartnerMember.role)
		.where(UserTable.name == user)
		.run(as_dict=True)
	)
	profile = rows[0] if rows else {}
	return {
		"email": user,
		"full_name": profile.get("full_name"),
		"user_image": profile.get("user_image"),
		"phone": profile.get("phone"),
		"role": profile.get("role"),
	}


def update_my_profile(full_name, phone=None, role=None):
	"""Lets any logged-in user edit their own profile details."""
	full_name = (full_name or "").strip()
	if not full_name:
		frappe.throw(_("Name can't be empty"))

	user = frappe.session.user
	frappe.db.set_value("User", user, {"full_name": full_name, "phone": (phone or "").strip()})

	member_name = frappe.db.get_value("Connect Partner Member", {"user": user}, "name")
	if member_name:
		frappe.db.set_value("Connect Partner Member", member_name, "role", (role or "").strip())

	return {"email": user, "full_name": full_name}


ALLOWED_PROFILE_IMAGE_EXTENSIONS = {
	".png": "image/png",
	".jpg": "image/jpeg",
	".jpeg": "image/jpeg",
	".gif": "image/gif",
	".webp": "image/webp",
}
MAX_PROFILE_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB


def upload_profile_image():
	"""Sets the caller's own profile photo from an uploaded image, stored publicly since avatars are shown to other users."""
	uploaded = frappe.request.files.get("file") if frappe.request else None
	if not uploaded:
		frappe.throw(_("No file was uploaded"))

	filename = uploaded.filename or ""
	ext = os.path.splitext(filename)[1].lower()
	if ext not in ALLOWED_PROFILE_IMAGE_EXTENSIONS:
		frappe.throw(_("Only PNG, JPG, GIF, and WEBP images can be used as a profile photo"))

	content = uploaded.stream.read()
	if len(content) > MAX_PROFILE_IMAGE_SIZE:
		frappe.throw(
			_("Image is too large — the limit is {0} MB").format(MAX_PROFILE_IMAGE_SIZE // (1024 * 1024))
		)

	user = frappe.session.user
	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": filename,
		"content": content,
		"is_private": 0,
		"attached_to_doctype": "User",
		"attached_to_name": user,
		"attached_to_field": "user_image",
	})
	file_doc.insert(ignore_permissions=True)

	frappe.db.set_value("User", user, "user_image", file_doc.file_url)
	return {"user_image": file_doc.file_url}


def get_my_context():
	"""Returns the caller's customer or partner company membership, or nulls for a guest."""
	user = frappe.session.user
	customer = get_customer_for_user(user)
	customer_membership = None
	if customer:
		is_admin = frappe.db.get_value("Customer Team Member", {"customer": customer, "user": user}, "is_admin")
		customer_name = frappe.db.get_value("Customer", customer, "customer_name")
		customer_membership = {"customer": customer, "customer_name": customer_name, "is_admin": cint(is_admin)}
	partner_membership = frappe.db.get_value(
		"Connect Partner Member", {"user": user}, ["partner", "is_admin"], as_dict=True
	)
	if partner_membership:
		partner_membership["partner_name"] = frappe.db.get_value("Partner", partner_membership.partner, "partner_name")
	return {
		"user": user,
		"customer": customer_membership,
		"partner": partner_membership,
	}
