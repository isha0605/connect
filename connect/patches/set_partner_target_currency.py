# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe.query_builder import Case
from frappe.query_builder.functions import IfNull

from connect.partner.doctype.partner.partner import INR_COUNTRY


def execute():
	"""Sets the target currency of partners that have none, by the rule a save uses: India uses INR,
	every other country USD."""
	partner = frappe.qb.DocType("Partner")
	(
		frappe.qb.update(partner)
		.set(partner.currency, Case().when(partner.country == INR_COUNTRY, "INR").else_("USD"))
		.where(IfNull(partner.currency, "") == "")
		.where(IfNull(partner.country, "") != "")
	).run()
