# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Countries Served is a new list, so every partner starts with none. The old count was typed in
	by hand with no list behind it, so it is reset to match the empty list."""
	partner = frappe.qb.DocType("Partner")
	frappe.qb.update(partner).set(partner.countries_served, 0).run()
