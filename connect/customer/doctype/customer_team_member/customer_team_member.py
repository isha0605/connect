# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from connect.membership import ADMIN, MEMBER, OWNER, CompanyMembership


class CustomerTeamMember(CompanyMembership, Document):
	COMPANY_FIELD = "customer"
	COMPANY_DOCTYPE = "Customer"
	SIDE = "Customer"
	ACCESS_LEVELS = (OWNER, ADMIN, MEMBER)

	def validate(self):
		self.validate_owner()

	def get_access_of(self, user: str) -> str | None:
		from connect.permissions import _customer_access_at

		return _customer_access_at(self.customer, user)
