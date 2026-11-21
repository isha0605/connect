# Copyright (c) 2026
# For license information, please see license.txt

import frappe

from connect.patches import set_app_logos

# Success stories on frappe.io name these apps, so the story fill needs them as Apps to match.
NEW_APPS = ("Frappe Lending", "Frappe Education")


def execute():
	"""Adds the apps success stories name that Connect lacks, then gives every app without a logo
	its icon, Frappe Framework's and Learning's included."""
	for app in NEW_APPS:
		if not frappe.db.exists("App", app):
			frappe.get_doc({"doctype": "App", "title": app}).insert()
	set_app_logos.execute()
