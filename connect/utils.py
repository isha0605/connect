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
	user_fields = frappe.db.get_value("User", user, ["full_name", "user_image", "phone"], as_dict=True) or {}

	doctype, _company, row = _my_company_membership(user)
	role = None
	if doctype:
		role_field = "designation" if doctype == "Customer Team Member" else "role"
		role = frappe.db.get_value(doctype, row.name, role_field)

	return {
		"email": user,
		"full_name": user_fields.get("full_name"),
		"user_image": user_fields.get("user_image"),
		"phone": user_fields.get("phone"),
		"role": role,
	}


def update_my_profile(full_name, phone=None, role=None):
	"""Lets any logged-in user edit their own profile details."""
	full_name = (full_name or "").strip()
	if not full_name:
		frappe.throw(_("Name can't be empty"))

	user = frappe.session.user
	frappe.db.set_value("User", user, {"full_name": full_name, "phone": (phone or "").strip()})

	doctype, _company, row = _my_company_membership(user)
	if doctype:
		role_field = "designation" if doctype == "Customer Team Member" else "role"
		frappe.db.set_value(doctype, row.name, role_field, (role or "").strip())

	return {"email": user, "full_name": full_name}


def upload_profile_image():
	"""Sets the caller's own profile photo from an uploaded image, stored publicly since avatars are shown to other users.

	Extension and size are enforced by the File doctype itself, from System Settings'
	allowed_file_extensions / max_file_size — not duplicated here.
	"""
	uploaded = frappe.request.files.get("file") if frappe.request else None
	if not uploaded:
		frappe.throw(_("No file was uploaded"))

	filename = uploaded.filename or ""
	content = uploaded.stream.read()

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


def get_partner_hours_for_thread(thread=None, dm_thread=None):
	"""Working hours for the partner side of one conversation — the customer-facing "are they
	around right now" signal, as opposed to Connect User Settings' get_my_settings (everyone's own
	personal hours). A company thread can have several partner team members; a DM has exactly one,
	and only if the other party happens to be a partner at all. Empty `members` means there's
	nothing to show: no partner on the thread yet, or (for a DM) the other person isn't a partner.
	"""
	from connect.messaging.doctype.connect_user_settings.connect_user_settings import get_settings_for_users

	partner_name = None
	partner_users = []

	if thread:
		members = frappe.get_all(
			"Connect Thread Member",
			filters={"thread": thread, "side": "Partner", "is_removed": 0},
			fields=["user"],
		)
		partner_users = [m.user for m in members]
		partner = frappe.db.get_value("Connect Thread", thread, "partner")
		if partner:
			partner_name = frappe.db.get_value("Partner", partner, "partner_name")
	elif dm_thread:
		user_a, user_b = frappe.db.get_value("Connect DM Thread", dm_thread, ["user_a", "user_b"])
		other = user_b if user_a == frappe.session.user else user_a
		partner = frappe.db.get_value("Connect Partner Member", {"user": other}, "partner")
		if partner:
			partner_users = [other]
			partner_name = frappe.db.get_value("Partner", partner, "partner_name")

	if not partner_users:
		return {"partner_name": None, "members": []}

	settings = get_settings_for_users(partner_users)
	return {
		"partner_name": partner_name,
		"members": [
			{"work_start": s["work_start"], "work_end": s["work_end"], "work_days": s["work_days"]}
			for s in settings.values()
		],
	}
