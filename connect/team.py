import frappe
from frappe import _
from frappe.utils import validate_email_address

from connect.crm_integration import crm_settings
from connect.partner.doctype.connect_partner_member.connect_partner_member import (
	ACCESS_LEVELS,
	FULL_ACCESS,
	MEMBER,
	OWNER,
	access_level_of,
)
from connect.permissions import (
	_is_customer_admin,
	_is_partner_admin,
	_is_partner_owner,
	_my_company_membership,
)


def get_my_company_members():
	"""Returns the caller's own company roster, used to populate the "transfer admin to" picker."""
	user = frappe.session.user
	doctype, company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	if doctype == "Customer Team Member":
		return frappe.get_all(doctype, filters={"customer": company}, fields=["user", "is_admin"])
	rows = frappe.get_all(doctype, filters={"partner": company}, fields=["user", "access"])
	return [{"user": row.user, "is_admin": access_level_of(row) in FULL_ACCESS} for row in rows]


def get_my_team():
	"""Returns the caller's own company roster with names and photos, to render the Settings Users list."""
	user = frappe.session.user
	doctype, company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	is_partner = doctype == "Connect Partner Member"
	fieldname = "partner" if is_partner else "customer"
	role_field = "role" if is_partner else "designation"

	Member = frappe.qb.DocType(doctype)
	UserTable = frappe.qb.DocType("User")
	columns = [
		Member.name, Member.user, Member.is_removed,
		Member[role_field].as_("role"), UserTable.full_name, UserTable.user_image, UserTable.last_login,
	]
	columns += [Member.access, Member.crm_user] if is_partner else [Member.is_admin]
	rows = (
		frappe.qb.from_(Member)
		.left_join(UserTable)
		.on(Member.user == UserTable.name)
		.select(*columns)
		.where(Member[fieldname] == company)
		.orderby(Member.creation, order=frappe.qb.asc)
		.run(as_dict=True)
	)
	# With CRM sync on, each partner member says whether they have a user on the CRM.
	has_crm = is_partner and bool(crm_settings(company))
	for row in rows:
		# Invited until they first sign in.
		row.is_invited = not row.pop("last_login")
		if is_partner:
			row.access_level = access_level_of(row)
			row.pop("access")
			row.is_admin = row.access_level in FULL_ACCESS
			row.in_crm = bool(row.pop("crm_user")) if has_crm else None

	# The people who run the company come first.
	if is_partner:
		return sorted(rows, key=lambda row: ACCESS_LEVELS.index(row.access_level))
	return sorted(rows, key=lambda row: not row.is_admin)


def remove_team_member(member):
	"""Removes someone from the caller's own company roster, on whichever side the caller belongs to."""
	user = frappe.session.user
	doctype, _company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	doc = frappe.get_doc(doctype, member)
	doc.remove(user)
	return {"removed": doc.user}


def add_team_member(email, role=None, password=None, full_name=None, access_level=None):
	"""Invites someone onto the caller's own company roster, creating their user account first if it doesn't exist.
	On a partner firm, `access_level` (Admin, Sales, Finance or Member) sets what they can do."""
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
	if not is_customer_side:
		access_level = _invite_access(access_level, company, user)

	email = (email or "").strip().lower()
	if not email:
		frappe.throw(_("Enter an email address"))
	if not validate_email_address(email, throw=False):
		frappe.throw(_("Enter a valid email address"))

	fieldname = "customer" if is_customer_side else "partner"
	existing = frappe.db.get_value(doctype, {fieldname: company, "user": email}, ["name", "is_removed"], as_dict=True)
	if existing and not existing.is_removed:
		frappe.throw(_("{0} is already a member").format(email))

	created_user = False
	if not frappe.db.exists("User", email):
		new_user = frappe.new_doc("User")
		new_user.email = email
		new_user.first_name = (full_name or "").strip() or email.split("@")[0]
		new_user.user_type = "Website User"
		new_user.send_welcome_email = 0
		if password:
			new_user.new_password = password
		new_user.insert(ignore_permissions=True)
		created_user = True

	role_field = "designation" if is_customer_side else "role"
	# Someone removed earlier keeps their row (one per company and user), so it's brought back.
	member_doc = frappe.get_doc(doctype, existing.name) if existing else frappe.new_doc(doctype)
	member_doc.update({fieldname: company, "user": email, "is_removed": 0, "removed_on": None})
	if role or not existing:
		member_doc.set(role_field, role)
	if is_customer_side:
		member_doc.is_admin = 0
	else:
		member_doc.access = access_level
	member_doc.save(ignore_permissions=True)

	return {"member": member_doc.name, "created_user": created_user}


def _invite_access(access_level, partner, user) -> str:
	"""The access a new partner member starts with. A firm's one Owner changes only by a
	transfer, and only the Owner adds an Admin."""
	level = access_level or MEMBER
	if level == OWNER:
		frappe.throw(_("A firm has one Owner. Invite them first, then transfer ownership."))
	if level not in ACCESS_LEVELS:
		frappe.throw(_("Pick Admin, Sales, Finance or Member"))
	if level in FULL_ACCESS and not _is_partner_owner(partner, user):
		frappe.throw(_("Only the Owner can add an Admin"), frappe.PermissionError)
	return level


def set_team_member_access(member, access_level):
	"""Changes what someone at the caller's own partner firm can do. Setting Owner hands them the firm."""
	user = frappe.session.user
	doctype, company, _row = _my_company_membership(user)
	if doctype != "Connect Partner Member":
		frappe.throw(_("Only a partner firm has access levels"), frappe.PermissionError)

	doc = frappe.get_doc("Connect Partner Member", member)
	if doc.partner != company:
		frappe.throw(_("{0} isn't on your team").format(doc.user), frappe.PermissionError)

	doc.set_access_level(access_level, user)
	return {"member": doc.name, "access_level": doc.access_level}
