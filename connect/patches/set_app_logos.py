# Copyright (c) 2026
# For license information, please see license.txt

import frappe

# Each app's own icon, shipped in connect/public/images/app_icons.
APP_ICONS = {
	"ERPNext": "erpnext.png",
	"Frappe HR": "frappe-hr.png",
	"Frappe CRM": "crm.png",
	"Helpdesk": "helpdesk.png",
	"Frappe Insights": "insights.png",
	"Frappe LMS": "learning.png",
	"Frappe Books": "frappe-books.png",
	"Frappe Drive": "frappe-drive.png",
	"Frappe Builder": "frappe-builder.png",
	"Wiki": "wiki.png",
}


def execute():
	"""Gives each app its logo, for the project questions' Apps list. Keeps one set by hand."""
	for app, icon in APP_ICONS.items():
		if frappe.db.exists("App", app) and not frappe.db.get_value("App", app, "logo"):
			frappe.db.set_value("App", app, "logo", f"/assets/connect/images/app_icons/{icon}", update_modified=False)
