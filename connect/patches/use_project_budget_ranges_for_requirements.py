# Copyright (c) 2026
# For license information, please see license.txt

import frappe

# Each old range moves to the project range its middle falls in.
OLD_TO_NEW = {
	"Under ₹2L": "Under ₹5 lakh",
	"₹2L–₹10L": "₹5 to 15 lakh",  # noqa: RUF001
	"₹10L–₹25L": "₹15 to 40 lakh",  # noqa: RUF001
	"₹25L–₹50L": "₹15 to 40 lakh",  # noqa: RUF001
	"₹50L+": "Over ₹40 lakh",
	"Not decided": "Not decided yet",
}


def execute():
	"""Requirements now use the project budget ranges, which come in rupees and dollars, instead of
	their own list."""
	requirement = frappe.qb.DocType("Requirement")
	for old, new in OLD_TO_NEW.items():
		frappe.qb.update(requirement).set(requirement.budget, new).where(requirement.budget == old).run()
