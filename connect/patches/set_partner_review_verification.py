# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Every review used to be marked verified. Now a review is "Hired on Connect" only when the
	reviewer's company hired the partner on Connect; the rest are "Not verified"."""
	Review = frappe.qb.DocType("Partner Review")
	Hire = frappe.qb.DocType("Partner Customer")
	hired = (
		frappe.qb.from_(Review)
		.join(Hire)
		.on((Hire.partner == Review.partner) & (Hire.customer == Review.customer) & (Hire.source == "Connect"))
		.select(Review.name)
		.run(pluck=True)
	)
	frappe.qb.update(Review).set(Review.verification, "Not verified").run()
	if hired:
		frappe.qb.update(Review).set(Review.verification, "Hired on Connect").where(Review.name.isin(hired)).run()
