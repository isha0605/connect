# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Success stories now keep the apps their frappe.io page lists. Reads them for the stories
	that exist already, in the background, since it fetches one page per story."""
	frappe.enqueue("connect.partner.story_apps.build_all_story_apps", queue="long")
