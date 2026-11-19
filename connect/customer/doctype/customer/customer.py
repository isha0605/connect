# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Customer(Document):
	def get_industries(self) -> list[str]:
		return [row.industry for row in self.industries]

	def get_company_facts(self) -> dict:
		"""What the project questions ask about the company: where it's based, its size and
		its industries. Every project starts from these."""
		return {"country": self.country or "", "company_size": self.company_size or "", "industries": self.get_industries()}

	def set_company_facts(self, facts: dict) -> None:
		"""A change in one project's answers updates the company's facts for the next."""
		if self._apply_company_facts(facts):
			# The caller's own company (get_customer_for_user); _apply_company_facts checked who may change it.
			self.save(ignore_permissions=True)

	def set_company_details(self, details: dict) -> None:
		"""Settings → Company details: its facts, and what it uses today."""
		self.current_system = details.get("current_system") or ""
		self._apply_company_facts(details)
		# The caller's own company (get_customer_for_user); _apply_company_facts checked who may change it.
		self.save(ignore_permissions=True)

	def get_company_details(self) -> dict:
		return {
			"company_name": self.customer_name,
			**self.get_company_facts(),
			"current_system": self.current_system,
			"can_change_facts": self.can_change_facts(frappe.session.user),
		}

	def can_change_facts(self, user: str) -> bool:
		"""Any member may fill in blank facts; only the Owner or an Admin may change set ones."""
		from connect.permissions import _is_customer_admin

		facts = self.get_company_facts()
		return not all(facts.values()) or _is_customer_admin(self.name, user)

	def _apply_company_facts(self, given: dict) -> bool:
		"""Sets the facts given, if this user may; returns whether they changed."""
		current = self.get_company_facts()
		facts = {
			"country": _country_name(given.get("country")) if "country" in given else current["country"],
			"company_size": (given.get("company_size") or "") if "company_size" in given else current["company_size"],
			"industries": list(given.get("industries") or []) if "industries" in given else current["industries"],
		}
		changed = [field for field, value in facts.items() if current[field] and current[field] != value]
		if changed and not self.can_change_facts(frappe.session.user):
			frappe.throw(
				_("Only your company's Owner or an Admin can change where it's based, its size or its industries."),
				frappe.PermissionError,
			)
		if facts == current:
			return False

		self.country = facts["country"]
		self.company_size = facts["company_size"]
		self.set("industries", [{"industry": industry} for industry in facts["industries"]])
		return True


def _country_name(country: str | None) -> str:
	"""The Country as Frappe names it ("india" is India), so it matches the partners' country."""
	country = (country or "").strip()
	return (frappe.db.get_value("Country", country, "name") if country else "") or country


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


def get_my_company_details() -> dict | None:
	customer = get_customer_for_user()
	return frappe.get_doc("Customer", customer).get_company_details() if customer else None


def save_my_company_details(details: dict) -> dict:
	customer = get_customer_for_user()
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)
	doc = frappe.get_doc("Customer", customer)
	doc.set_company_details(details)
	return doc.get_company_details()


def get_my_customer():
	"""Current session user's Customer company — feeds the portal shell (sidebar identity etc)."""
	customer = get_customer_for_user()
	if not customer:
		return None
	return frappe.db.get_value("Customer", customer, ["name", "customer_name"], as_dict=True)
