# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Customer(Document):
	def get_industries(self) -> list[str]:
		return [row.industry for row in self.industries]

	def set_company_facts(self, company_size: str, industries: list[str]) -> None:
		"""What the project questions ask about the company: its size and industries. Every
		project starts from these, and a change in one project updates them for the next."""
		if self.company_size == company_size and self.get_industries() == industries:
			return

		self.company_size = company_size
		self.set("industries", [{"industry": industry} for industry in industries])
		# Callers pass the caller's own company (get_customer_for_user), which any member may describe.
		self.save(ignore_permissions=True)


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


def get_customer_for_user(user=None):
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
