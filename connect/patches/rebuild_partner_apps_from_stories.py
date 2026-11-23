# Copyright (c) 2026
# For license information, please see license.txt

import frappe

from connect.partner.story_apps import refresh_partner_apps


def execute():
	"""A partner's apps now come only from its success stories. Rebuilds them from the stories each
	partner has; an app picked by hand that no story names is dropped."""
	for partner in frappe.get_all("Partner", pluck="name"):
		refresh_partner_apps(partner)
