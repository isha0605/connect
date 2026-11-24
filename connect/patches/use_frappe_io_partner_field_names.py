# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe.model.utils.rename_field import rename_field
from frappe.query_builder.functions import Count

# Old Partner field -> the frappe.io name it now has (frappe.io's custom_ prefix left out).
RENAMED_FIELDS = {
	"rollouts": "successful_projects_count",
	"sites_deployed": "total_sites_count",
	"certified_experts": "number_of_certified_members",
	"certs_erpnext": "erpnext_certified",
	"certs_frappe_framework": "framework_certified",
}


def execute():
	"""Gives Partner frappe.io's field names. partner_name held the company and now holds the Owner's
	name, as on frappe.io, so the company moves to company_name first. Safe to re-run."""
	move_company_names()
	set_owner_names()
	for old, new in RENAMED_FIELDS.items():
		move_column(old, new)


def move_company_names():
	# Runs once: after it, every partner has a company_name, and partner_name holds a person.
	partner = frappe.qb.DocType("Partner")
	moved = frappe.qb.from_(partner).select(Count("*")).where(partner.company_name.notnull()).run()[0][0]
	if not moved:
		frappe.qb.update(partner).set(partner.company_name, partner.partner_name).run()


def set_owner_names():
	from connect.partner.doctype.connect_partner_member.connect_partner_member import set_owner_on_partner

	for partner in frappe.get_all("Partner", pluck="name"):
		set_owner_on_partner(partner)


def move_column(old: str, new: str) -> None:
	"""Copies a renamed field's values, checks they all moved, then drops the old column."""
	if not frappe.db.has_column("Partner", old):
		return

	rename_field("Partner", old, new)
	# rename_field copies with no check, so compare before the old values are dropped.
	partner = frappe.qb.DocType("Partner")
	differs = (
		frappe.qb.from_(partner).select(Count("*")).where(partner[old].notnull() & (partner[old] != partner[new]))
	).run()[0][0]
	if differs:
		frappe.throw(f"Some Partner.{old} values did not move to {new}. Kept {old}. Run bench migrate again.")

	frappe.db.sql_ddl(f"alter table `tabPartner` drop column `{old}`")
	frappe.client_cache.delete_value("table_columns::tabPartner")
