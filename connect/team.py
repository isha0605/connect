import frappe
from frappe import _
from frappe.model.document import get_controller
from frappe.utils import validate_email_address

from connect.crm_integration import crm_settings
from connect.membership import FULL_ACCESS, MEMBER
from connect.permissions import _my_company_membership

# Each side's team row: the field naming its company and the person's free-text job title.
COMPANY_FIELD = {"Connect Partner Member": "partner", "Customer Team Member": "customer"}
ROLE_FIELD = {"Connect Partner Member": "role", "Customer Team Member": "designation"}


def get_my_company_members():
	"""Returns the caller's own company roster, used to populate the "transfer admin to" picker."""
	doctype, company = _my_company()
	rows = frappe.get_all(doctype, filters={COMPANY_FIELD[doctype]: company}, fields=["user", "access"])
	return [{"user": row.user, "is_admin": row.access in FULL_ACCESS} for row in rows]


def get_my_team():
	"""Returns the caller's own company roster with names and photos, to render the Settings Users list."""
	doctype, company = _my_company()
	is_partner = doctype == "Connect Partner Member"

	Member = frappe.qb.DocType(doctype)
	UserTable = frappe.qb.DocType("User")
	columns = [
		Member.name, Member.user, Member.is_removed, Member.access,
		Member[ROLE_FIELD[doctype]].as_("role"), UserTable.full_name, UserTable.user_image, UserTable.last_login,
	]
	if is_partner:
		columns.append(Member.crm_user)
	rows = (
		frappe.qb.from_(Member)
		.left_join(UserTable)
		.on(Member.user == UserTable.name)
		.select(*columns)
		.where(Member[COMPANY_FIELD[doctype]] == company)
		.orderby(Member.creation, order=frappe.qb.asc)
		.run(as_dict=True)
	)
	# With CRM sync on, each partner member says whether they have a user on the CRM.
	has_crm = is_partner and bool(crm_settings(company))
	for row in rows:
		# Invited until they first sign in.
		row.is_invited = not row.pop("last_login")
		row.access_level = row.pop("access") or MEMBER
		row.is_admin = row.access_level in FULL_ACCESS
		if is_partner:
			row.in_crm = bool(row.pop("crm_user")) if has_crm else None

	# The people who run the company come first.
	levels = get_controller(doctype).ACCESS_LEVELS
	return sorted(rows, key=lambda row: levels.index(row.access_level))


def remove_team_member(member):
	"""Removes someone from the caller's own company roster, on whichever side the caller belongs to."""
	doctype, _company = _my_company()
	doc = frappe.get_doc(doctype, member)
	doc.remove(frappe.session.user)
	return {"removed": doc.user}


def add_team_member(email, role=None, password=None, full_name=None, access_level=None):
	"""Invites someone onto the caller's own company roster, creating their user account first if
	it doesn't exist. `access_level` sets what they can do: Admin or Member, and on a partner firm
	also Sales or Finance."""
	doctype, company = _my_company()
	fieldname = COMPANY_FIELD[doctype]
	invite = frappe.new_doc(doctype)
	invite.update({fieldname: company, "access": access_level or MEMBER})
	invite.check_can_invite(frappe.session.user)
	email = _clean_email(email)

	existing = frappe.db.get_value(doctype, {fieldname: company, "user": email}, ["name", "is_removed"], as_dict=True)
	if existing and not existing.is_removed:
		frappe.throw(_("{0} is already a member").format(email))
	created_user = _make_user(email, full_name, password)

	# Someone removed earlier keeps their row (one per company and user), so it's brought back.
	member_doc = frappe.get_doc(doctype, existing.name) if existing else invite
	member_doc.update(
		{fieldname: company, "user": email, "access": invite.access, "is_removed": 0, "removed_on": None}
	)
	if role or not existing:
		member_doc.set(ROLE_FIELD[doctype], role)
	member_doc.save(ignore_permissions=True)

	return {"member": member_doc.name, "created_user": created_user}


def set_team_member_access(member, access_level):
	"""Changes what someone at the caller's own company can do. Setting Owner hands them the company."""
	doctype, company = _my_company()
	doc = frappe.get_doc(doctype, member)
	if doc.get(COMPANY_FIELD[doctype]) != company:
		frappe.throw(_("{0} isn't on your team").format(doc.user), frappe.PermissionError)

	doc.set_access_level(access_level, frappe.session.user)
	return {"member": doc.name, "access_level": doc.access_level}


def _my_company() -> tuple[str, str]:
	"""The caller's team row doctype and company."""
	doctype, company, _row = _my_company_membership(frappe.session.user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))
	return doctype, company


def _clean_email(email) -> str:
	email = (email or "").strip().lower()
	if not email:
		frappe.throw(_("Enter an email address"))
	if not validate_email_address(email, throw=False):
		frappe.throw(_("Enter a valid email address"))
	return email


def _make_user(email, full_name, password) -> bool:
	"""Creates the invited person's website account unless they have one. Whether it was made."""
	if frappe.db.exists("User", email):
		return False

	new_user = frappe.new_doc("User")
	new_user.email = email
	new_user.first_name = (full_name or "").strip() or email.split("@")[0]
	new_user.user_type = "Website User"
	new_user.send_welcome_email = 0
	if password:
		new_user.new_password = password
	new_user.insert(ignore_permissions=True)
	return True
