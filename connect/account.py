import frappe
from frappe import _
from frappe.utils import cint

from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.notifications import CONNECT_NOTIFICATION_DOCTYPES
from connect.permissions import _my_company_membership


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
		"Connect Partner Member", {"user": user, "is_removed": 0}, ["partner", "is_admin"], as_dict=True
	)
	if partner_membership:
		partner_membership["partner_name"] = frappe.db.get_value("Partner", partner_membership.partner, "partner_name")
	signed_in = user != "Guest"
	projects_route = get_projects_route(user, customer) if signed_in else None
	return {
		"user": user,
		"full_name": frappe.db.get_value("User", user, "full_name") if signed_in else None,
		"customer": customer_membership,
		"partner": partner_membership,
		# The sidebar's Projects item: shown once the buyer has something to show there.
		"has_projects": bool(projects_route),
		"projects_route": projects_route,
		"unread_notifications": frappe.db.count(
			"Notification Log",
			{"for_user": user, "read": 0, "document_type": ["in", CONNECT_NOTIFICATION_DOCTYPES]},
		)
		if signed_in
		else 0,
	}


def get_projects_route(user, customer=None):
	"""Where the sidebar's Projects goes — the projects list — once the buyer has something
	there: a paid Starter Pack order, a project of their own, or saved requirements. Else
	nowhere (no Projects)."""
	or_filters = {"user": user}
	if customer:
		or_filters["customer"] = customer
	has_order = frappe.get_all(
		"Starter Pack Order",
		filters={"payment_status": ["in", ["Paid", "Partially Refunded"]]},
		or_filters=or_filters,
		limit=1,
		pluck="name",
	)
	if (
		has_order
		or frappe.db.exists("Customer Project", {"user": user})
		or (customer and frappe.db.exists("Requirement", {"customer": customer}))
	):
		return "/projects"
	return None
