# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.model.document import Document


class PartnerCertificate(Document):
	@staticmethod
	def get_list_query(query):
		Partner = frappe.qb.DocType("Partner")
		PartnerCertificate = frappe.qb.DocType("Partner Certificate")
		return query.left_join(Partner).on(PartnerCertificate.partner == Partner.name).select(
			Partner.partner_name
		)
