import os
import frappe
from frappe import _
from frappe.utils import cint

ALLOWED_PROFILE_IMAGE_EXTENSIONS = {
	".png": "image/png",
	".jpg": "image/jpeg",
	".jpeg": "image/jpeg",
	".gif": "image/gif",
	".webp": "image/webp",
}
MAX_PROFILE_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB


def _my_company_membership(user: str):
	"""Returns (doctype, company, row) for whichever company this user belongs to, or
	(None, None, None) if neither. A user is assumed to belong to at most one company."""
	customer_row = frappe.db.get_value(
		"Customer Team Member", {"user": user}, ["name", "customer", "is_admin"], as_dict=True
	)
	if customer_row:
		return "Customer Team Member", customer_row.customer, customer_row
	partner_row = frappe.db.get_value(
		"Connect Partner Member", {"user": user}, ["name", "partner", "is_admin"], as_dict=True
	)
	if partner_row:
		return "Connect Partner Member", partner_row.partner, partner_row
	return None, None, None


def _my_side(user):
	"""Which side (Customer/Partner) this user belongs to, or None if neither."""
	doctype, _company, _row = _my_company_membership(user)
	if doctype == "Customer Team Member":
		return "Customer"
	if doctype == "Connect Partner Member":
		return "Partner"
	return None


def get_my_company_members():
	"""The caller's own company roster (Customer Member or Partner Member rows) — used to
	populate the 'transfer admin to' picker. Not thread-scoped, unlike everything else here."""
	user = frappe.session.user
	doctype, company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	fieldname = "customer" if doctype == "Customer Team Member" else "partner"
	return frappe.get_all(doctype, filters={fieldname: company}, fields=["user", "is_admin"])


def get_my_team():
	"""The caller's own company roster, enriched with name/photo — powers the sidebar
	Settings popup's Users section. Unlike get_my_company_members (a bare user/is_admin list
	for the 'transfer admin to' picker), this is meant to render directly."""
	user = frappe.session.user
	doctype, company, _row = _my_company_membership(user)
	if not doctype:
		frappe.throw(_("You are not a member of any company"))

	fieldname = "customer" if doctype == "Customer Team Member" else "partner"
	Member = frappe.qb.DocType(doctype)
	UserTable = frappe.qb.DocType("User")

	return (
		frappe.qb.from_(Member)
		.left_join(UserTable)
		.on(Member.user == UserTable.name)
		.select(Member.user, Member.is_admin, UserTable.full_name, UserTable.user_image)
		.where(Member[fieldname] == company)
		.run(as_dict=True)
	)


def get_my_profile():
	"""The caller's own name/photo/contact details — powers the sidebar avatar and the
	Settings popup's Profile section. `role` is company-scoped (Connect Partner Member),
	not a User field, so it's looked up separately and only set for partner-side users."""
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


def update_my_profile(full_name: str, phone: str | None = None, role: str | None = None):
	"""Self-service profile edit — matches the Profile section in the Settings popup. Any
	logged-in user may edit themselves; there's nothing company- or thread-scoped to check
	here. `role` only persists for partner-side users (it lives on their Connect Partner
	Member row); it's silently ignored for anyone without one."""
	full_name = (full_name or "").strip()
	if not full_name:
		frappe.throw(_("Name can't be empty"))

	user = frappe.session.user
	frappe.db.set_value("User", user, {"full_name": full_name, "phone": (phone or "").strip()})

	member_name = frappe.db.get_value("Connect Partner Member", {"user": user}, "name")
	if member_name:
		frappe.db.set_value("Connect Partner Member", member_name, "role", (role or "").strip())

	return {"email": user, "full_name": full_name}


def upload_profile_image():
	"""Sets the caller's own User.user_image from an uploaded file — powers the clickable
	avatar in the Settings popup's Profile section. Stored as a public file since avatars are
	rendered to other users across the app (thread lists, member rows, hover cards)."""
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
	"""customer side reads real Customer Team Member membership (the doctype the rest of
	the app — Requirement, Shortlist, Pricing — already uses); partner side reads
	Connect Partner Member (the real partner-side user/login model, see
	_is_partner_admin/_is_partner_member in connect.permissions). Guest-safe: an
	unrecognized/Guest user just falls through to customer=None, partner=None."""
	user = frappe.session.user
	from connect.customer.doctype.customer.customer import get_customer_for_user
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
