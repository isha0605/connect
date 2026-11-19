# Copyright (c) 2026
# For license information, please see license.txt

import frappe

SYSTEMS = (
	"Tally",
	"Zoho",
	"QuickBooks",
	"Busy",
	"SAP",
	"Microsoft Dynamics",
	"Odoo",
	"Salesforce",
	"An in-house system",
	"Something else",
)


def execute():
	"""A new project is shared as it is saved, so there are no drafts any more: deletes every
	draft, unlinking any Starter Pack Order that pointed at one. Also moves "What do you use
	today?" from each customer's Requirement onto the Customer."""
	drafts = frappe.get_all("Customer Project", filters={"status": "Draft"}, pluck="name")
	if drafts:
		frappe.db.set_value(
			"Starter Pack Order",
			{"customer_project": ["in", drafts]},
			"customer_project",
			None,
			update_modified=False,
		)
	for name in drafts:
		# A migration, with nobody signed in whose access applies.
		frappe.delete_doc("Customer Project", name, ignore_permissions=True, force=True)

	for customer in frappe.get_all("Customer", filters={"current_system": ["in", ["", None]]}, pluck="name"):
		system = frappe.db.get_value(
			"Requirement", {"customer": customer}, "current_situation", order_by="creation desc"
		)
		if system in SYSTEMS:
			frappe.db.set_value("Customer", customer, "current_system", system, update_modified=False)
