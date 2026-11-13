# Copyright (c) 2026
# For license information, please see license.txt

import shutil

import frappe

# Where logos were cached before connect.partner.logo.CACHE_FOLDER moved on.
OLD_CACHE_FOLDER = "partner-logos"


def execute():
	"""Client logos are now stripped of boxes of any colour and sized by their ink weight.
	Builds them all again in the background and removes the copies made the old way."""
	shutil.rmtree(frappe.get_site_path("public", "files", OLD_CACHE_FOLDER), ignore_errors=True)
	frappe.enqueue("connect.partner.logo.build_all_logos", queue="long")
