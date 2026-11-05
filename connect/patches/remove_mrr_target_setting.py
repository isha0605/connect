import frappe


def execute():
	"""The minimum MRR is fixed by the partner's country now, not set in Integration Settings."""
	frappe.db.delete("Singles", {"doctype": "Integration Settings", "field": "mrr_target"})
