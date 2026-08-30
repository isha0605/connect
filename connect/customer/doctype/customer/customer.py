# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import validate_email_address


class Customer(Document):
	pass


def get_permission_query_conditions(user):
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return ""
	return f"""`tabCustomer`.name in (
		select customer from `tabCustomer Team Member` where user = {frappe.db.escape(user)}
	)"""


def has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return True
	return bool(frappe.db.exists("Customer Team Member", {"customer": doc.name, "user": user}))


def get_customer_for_user(user: str | None = None):
	"""Customer company the given (or current session) user belongs to, via Customer Team Member."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return None
	return frappe.db.get_value("Customer Team Member", {"user": user}, "customer")


def get_my_customer():
	"""Current session user's Customer company — feeds the portal shell (sidebar identity etc)."""
	customer = get_customer_for_user()
	if not customer:
		return None
	return frappe.db.get_value("Customer", customer, ["name", "customer_name"], as_dict=True)


def signup_customer(full_name: str, company_name: str, email: str, password: str):
	"""Self-serve signup for a new customer company: creates the User and a new
	Customer, seats the signing-up user as that Customer's admin, and logs them
	in immediately."""
	full_name = (full_name or "").strip()
	company_name = (company_name or "").strip()
	email = (email or "").strip().lower()
	if not full_name or not company_name or not email or not password:
		frappe.throw(_("Please fill in all fields"))
	if not validate_email_address(email, throw=False):
		frappe.throw(_("Enter a valid email address"))
	if frappe.db.exists("User", email):
		frappe.throw(_("An account with this email already exists. Log in instead."))
	if frappe.db.exists("Customer", company_name):
		frappe.throw(
			_("{0} is already registered. Ask your team admin to add you instead.").format(company_name)
		)

	first_name, _, last_name = full_name.partition(" ")

	user = frappe.new_doc("User")
	user.email = email
	user.first_name = first_name
	user.last_name = last_name
	user.user_type = "Website User"
	user.send_welcome_email = 0
	user.new_password = password
	user.insert(ignore_permissions=True)

	customer = frappe.new_doc("Customer")
	customer.customer_name = company_name
	customer.insert(ignore_permissions=True)

	frappe.get_doc({
		"doctype": "Customer Team Member",
		"customer": customer.name,
		"user": email,
		"full_name": full_name,
		"is_admin": 1,
	}).insert(ignore_permissions=True)

	frappe.local.login_manager.login_as(email)
	return {"ok": True}
