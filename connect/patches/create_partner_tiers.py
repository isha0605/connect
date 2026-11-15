# Copyright (c) 2026
# For license information, please see license.txt

import frappe

# Title -> (target in INR, target in USD, certificates required, PMM level required). The targets are
# the ones frappe.io's "Upgrade Partner Level" script sets tiers by. Beginner is Connect's own: a partner
# who registers in Connect starts there.
TIERS = {
	"Gold": (630000, 7500, 4, 5),
	"Silver": (250000, 3150, 3, 4),
	"Bronze": (63000, 750, 2, 3),
	"Emerging": (30000, 350, 2, 2),
	"Entry": (0, 0, 2, 2),
	"Beginner": (0, 0, 0, 0),
}


def execute():
	"""Creates the partner tiers. Skips a tier that exists, so it never undoes edits made in Desk."""
	for title, (target_in_inr, target_in_usd, certificates_required, pmm_required) in TIERS.items():
		if frappe.db.exists("Partner Tier", title):
			continue

		frappe.get_doc({
			"doctype": "Partner Tier",
			"title": title,
			"target_in_inr": target_in_inr,
			"target_in_usd": target_in_usd,
			"certificates_required": certificates_required,
			"pmm_required": pmm_required,
		}).insert(ignore_permissions=True)  # a migration runs as Administrator with no request
