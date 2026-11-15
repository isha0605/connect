# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Requirement stops keeping its own company name and country; the Customer owns them. A
	Customer with no country takes the one its latest Requirement has. Where both have a country,
	the Customer's stays."""
	if not frappe.db.has_column("Requirement", "country"):
		return

	Requirement = frappe.qb.DocType("Requirement")
	Customer = frappe.qb.DocType("Customer")
	rows = (
		frappe.qb.from_(Requirement)
		.join(Customer)
		.on(Customer.name == Requirement.customer)
		.select(Requirement.customer, Requirement.country)
		.where((Customer.country.isnull()) | (Customer.country == ""))
		.where(Requirement.country.isnotnull() & (Requirement.country != ""))
		.orderby(Requirement.creation, order=frappe.qb.desc)
		.run(as_dict=True)
	)

	latest = {}
	for row in rows:
		latest.setdefault(row.customer, row.country.strip())

	for customer, country in latest.items():
		frappe.db.set_value("Customer", customer, "country", country, update_modified=False)
