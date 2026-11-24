# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Fills the new Owner Email on every partner from its team's Owner."""
	from connect.partner.doctype.connect_partner_member.connect_partner_member import set_owner_on_partner

	for partner in frappe.get_all("Partner", pluck="name"):
		set_owner_on_partner(partner)
