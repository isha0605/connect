# Copyright (c) 2026
# For license information, please see license.txt

import frappe

# The old en-dash ranges, two of which overlapped, mapped to the ranges Partner and Enquiry use.
# 201–1000 goes to the lower range, so a company is never shown as bigger than it said.
OLD_TO_NEW = {
	"1–10": "1-10",  # noqa: RUF001
	"11–50": "11-50",  # noqa: RUF001
	"51–200": "51-200",  # noqa: RUF001
	"201–500": "201-500",  # noqa: RUF001
	"201–1000": "201-500",  # noqa: RUF001
	"1000+": "500+",
}


def execute():
	Requirement = frappe.qb.DocType("Requirement")
	for old, new in OLD_TO_NEW.items():
		frappe.qb.update(Requirement).set(Requirement.company_size, new).where(Requirement.company_size == old).run()
