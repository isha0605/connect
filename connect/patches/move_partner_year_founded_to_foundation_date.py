# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe.query_builder.functions import Count


def execute():
	"""Moves each Partner's year_founded to foundation_date as 1 January of that year, since the day and
	month are not known. Moves it in unpublished profile drafts too, checks every year moved, then drops
	the old column. Safe to re-run."""
	if not frappe.db.has_column("Partner", "year_founded"):
		return

	partner = frappe.qb.DocType("Partner")
	years = (
		frappe.qb.from_(partner)
		.select(partner.name, partner.year_founded)
		.where(partner.year_founded > 0)
		.where(partner.foundation_date.isnull())
	).run()
	for name, year in years:
		frappe.db.set_value("Partner", name, "foundation_date", f"{int(year):04d}-01-01", update_modified=False)
	move_year_in_drafts()

	if count_moved() < count_with_year():
		frappe.throw("Only some Partner.year_founded values moved to foundation_date. Kept year_founded. Run bench migrate again.")

	frappe.db.sql_ddl("alter table `tabPartner` drop column `year_founded`")
	frappe.client_cache.delete_value("table_columns::tabPartner")


def move_year_in_drafts():
	for name, draft in frappe.get_all("Partner", filters={"profile_draft": ["like", '%"year_founded"%']}, fields=["name", "profile_draft"], as_list=True):
		values = frappe.parse_json(draft)
		year = values.pop("year_founded", None)
		if year:
			values["foundation_date"] = f"{int(year):04d}-01-01"
		frappe.db.set_value("Partner", name, "profile_draft", frappe.as_json(values), update_modified=False)


def count_with_year() -> int:
	# Reads the column directly: year_founded is no longer a Partner field, so frappe.db.count rejects it.
	partner = frappe.qb.DocType("Partner")
	return frappe.qb.from_(partner).select(Count("*")).where(partner.year_founded > 0).run()[0][0]


def count_moved() -> int:
	partner = frappe.qb.DocType("Partner")
	return (
		frappe.qb.from_(partner)
		.select(Count("*"))
		.where(partner.year_founded > 0)
		.where(partner.foundation_date.notnull())
	).run()[0][0]
