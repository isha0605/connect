# Copyright (c) 2026
# For license information, please see license.txt

import frappe

# frappe.io's success-story industries (frappe.io/stories), in the groups the questionnaire shows.
# Each group is an Industry too, so a partner or business can pick a whole group.
INDUSTRY_GROUPS = {
	"Manufacturing": [
		"Automotive Manufacturing", "Chemical Manufacturing", "Discrete Manufacturing", "Electronics Manufacturing",
		"Food and Beverages", "Furniture Manufacturing", "Jewellery Manufacturing", "Medical Device Manufacturing",
		"Pharmaceutical Manufacturing", "Process Manufacturing", "Steel Manufacturing", "Textile Manufacturing",
	],
	"Services": [
		"Aviation Industry", "Banking, Insurance and Broking", "Consulting", "Education", "Government",
		"Healthcare", "Hotels, Restaurants and Cafes", "Logistics", "Nonprofit", "Professional services",
		"Real Estate", "Rental Business", "Software Development", "Telecommunications",
	],
	"Trading and Distribution": ["E-commerce", "Fast Moving Consumer Goods", "Goods Trading", "Retail"],
	"Others": ["Agriculture", "Engineering and Construction", "Livestock"],
}
GROUP_OF = {member: group for group, members in INDUSTRY_GROUPS.items() for member in members}
INDUSTRIES = set(INDUSTRY_GROUPS) | set(GROUP_OF)

# Old Requirement, Customer and Industry values, and the industry each now is.
RENAMED = {
	"Finance": "Banking, Insurance and Broking",
	"FinTech": "Banking, Insurance and Broking",
	"Hospitality": "Hotels, Restaurants and Cafes",
	"Technology": "Software Development",
	"Distribution": "Goods Trading",
	"Retail & Distribution": "Trading and Distribution",
	"Construction": "Engineering and Construction",
	"Other": "Others",
	"Professional Services": "Professional services",
}
SINGLE_VALUE_FIELDS = (("Requirement", "industry"), ("Customer", "industry"))


def execute():
	"""Makes the Industry list frappe.io's success-story industries, now that Requirement.industry
	and Customer.industry link to it. Renames old values everywhere an industry is stored, then
	deletes the Industry records outside the list.

	Stops before deleting anything if a stored value is neither in the list nor renamed, so that
	value can be placed by hand. Safe to re-run."""
	create_industries()
	for doctype, fieldname in SINGLE_VALUE_FIELDS:
		for old, new in RENAMED.items():
			frappe.db.set_value(doctype, {fieldname: old}, fieldname, new, update_modified=False)
	_rename_partner_industries()
	_rename_in_projects()

	check_every_value_is_listed()
	for name in frappe.get_all("Industry", filters={"name": ["not in", list(INDUSTRIES)]}, pluck="name"):
		frappe.delete_doc("Industry", name, force=True, ignore_permissions=True)


def create_industries():
	"""Creates the list and sets each industry's group. Also run on install, which skips patches.
	Groups come first, so each member's group exists when the member is saved."""
	for name in [*INDUSTRY_GROUPS, *GROUP_OF]:
		group = GROUP_OF.get(name)
		if not frappe.db.exists("Industry", name):
			frappe.get_doc({"doctype": "Industry", "title": name, "industry_group": group}).insert(
				ignore_permissions=True
			)
		elif frappe.db.get_value("Industry", name, "industry_group") != group:
			frappe.db.set_value("Industry", name, "industry_group", group, update_modified=False)


def _rename_partner_industries():
	"""A partner who picked both an old name and its new one keeps a single row."""
	rows = frappe.get_all(
		"Partner Industry",
		filters={"parentfield": "industries", "industry": ["in", list(RENAMED)]},
		fields=["name", "parent", "industry"],
	)
	for row in rows:
		# MariaDB matches names case-insensitively, so a row may already hold the new name.
		new = RENAMED.get(row.industry)
		if not new:
			continue
		if frappe.db.exists("Partner Industry", {"parent": row.parent, "parentfield": "industries", "industry": new}):
			frappe.db.delete("Partner Industry", {"name": row.name})
		else:
			frappe.db.set_value("Partner Industry", row.name, "industry", new, update_modified=False)


def _rename_in_projects():
	"""A project keeps industries twice: the questionnaire's answers and its Edit criteria."""
	for project in frappe.get_all("Customer Project", fields=["name", "industries", "criteria"]):
		industries = frappe.parse_json(project.industries or "[]") or []
		criteria = frappe.parse_json(project.criteria or "{}") or {}
		changes = {}

		if _renamed(industries) != industries:
			changes["industries"] = frappe.as_json(_renamed(industries))
		if _renamed(criteria.get("industries") or []) != (criteria.get("industries") or []):
			criteria["industries"] = _renamed(criteria["industries"])
			changes["criteria"] = frappe.as_json(criteria)

		if changes:
			frappe.db.set_value("Customer Project", project.name, changes, update_modified=False)


def _renamed(industries: list[str]) -> list[str]:
	return list(dict.fromkeys(RENAMED.get(industry, industry) for industry in industries))


def check_every_value_is_listed() -> None:
	unlisted = {}
	for doctype, fieldname in (*SINGLE_VALUE_FIELDS, ("Partner Industry", "industry")):
		values = frappe.get_all(doctype, filters={fieldname: ["is", "set"]}, pluck=fieldname, distinct=True)
		unlisted.update({value: doctype for value in values if value not in INDUSTRIES})

	for project in frappe.get_all("Customer Project", fields=["industries", "criteria"]):
		criteria = frappe.parse_json(project.criteria or "{}") or {}
		stored = (frappe.parse_json(project.industries or "[]") or []) + (criteria.get("industries") or [])
		unlisted.update({value: "Customer Project" for value in stored if value not in INDUSTRIES})

	if unlisted:
		found = ", ".join(f"{value} ({doctype})" for value, doctype in sorted(unlisted.items()))
		frappe.throw(
			f"These industries are not in frappe.io's list and have no new name: {found}. "
			"Add each to RENAMED in this patch, then run the migration again.",
			title="Industries not placed",
		)
