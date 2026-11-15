# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe.utils import today


def execute():
	"""Gives partners already on the website today as their listed date, so their 90 days before
	the daily review may hide them start now."""
	partner = frappe.qb.DocType("Partner")
	(
		frappe.qb.update(partner)
		.set(partner.listed_on, today())
		.where(partner.show_in_website == 1)
		.where(partner.listed_on.isnull())
	).run()
