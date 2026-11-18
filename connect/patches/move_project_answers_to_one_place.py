# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe.query_builder import Order

# The project questions stored the number of employees as its label; Customer keeps the value.
COMPANY_SIZE_VALUES = {
	"1 to 10": "1-10",
	"11 to 50": "11-50",
	"51 to 200": "51-200",
	"201 to 500": "201-500",
	"More than 500": "500+",
}
COMPANY_SIZES = set(COMPANY_SIZE_VALUES.values())


def execute():
	"""Moves each answer to its one place: regions and work mode out of a project's criteria,
	and the number of employees and industries from projects onto their Customer. A company
	whose projects disagree keeps what its newest project said. Safe to re-run."""
	# Company facts first: they fall back to the industries Edit criteria kept in criteria.
	for customer in frappe.get_all("Customer", pluck="name"):
		_move_company_facts(customer)
		_copy_requirement_apps(customer)

	for project in frappe.get_all("Customer Project", fields=["name", "criteria", "regions"]):
		_split_criteria(project)


def _split_criteria(project) -> None:
	criteria = frappe.parse_json(project.criteria or "{}") or {}
	if project.regions or not criteria:
		return
	frappe.db.set_value(
		"Customer Project",
		project.name,
		{
			"regions": frappe.as_json(criteria.get("countries") or []),
			"work_modes": frappe.as_json(criteria.get("work") or []),
			"criteria": frappe.as_json(
				{"cities": criteria.get("cities") or [], "tiers": criteria.get("tiers") or []}
			),
		},
		update_modified=False,
	)


def _move_company_facts(customer: str) -> None:
	doc = frappe.get_doc("Customer", customer)
	if doc.company_size and doc.industries:
		return
	projects = _team_project_answers(customer)
	size = doc.company_size or _newest_company_size(projects) or _requirement_company_size(customer)
	industries = doc.get_industries() or _newest_industries(customer, projects)
	if (size or "") == (doc.company_size or "") and industries == doc.get_industries():
		return

	doc.company_size = size or ""
	doc.set("industries", [{"industry": name} for name in industries])
	# A migration, with nobody signed in whose access applies.
	doc.save(ignore_permissions=True)


def _copy_requirement_apps(customer: str) -> None:
	"""A customer's apps lived on their one Requirement; each of their projects now has its own."""
	requirement = frappe.db.get_value("Requirement", {"customer": customer}, "name", order_by="creation desc")
	apps = requirement and frappe.get_all(
		"Partner App",
		filters={"parenttype": "Requirement", "parent": requirement, "parentfield": "apps"},
		pluck="app",
		order_by="idx asc",
	)
	if not apps:
		return
	projects = frappe.get_all(
		"Customer Project", filters={"user": ["in", _team(customer) or [""]]}, pluck="name"
	)
	for project in projects:
		if frappe.db.exists("Partner App", {"parenttype": "Customer Project", "parent": project}):
			continue
		# Rows only: saving the project would notify partners and send analytics events.
		for idx, app in enumerate(apps, start=1):
			frappe.get_doc(
				{
					"doctype": "Partner App",
					"parenttype": "Customer Project",
					"parentfield": "apps",
					"parent": project,
					"idx": idx,
					"app": app,
				}
			).db_insert()


def _team_project_answers(customer: str) -> list[dict]:
	"""The team's projects, newest first, with the company answers this patch moves off them.
	A project saved before these questions holds "" or [] instead of nothing."""
	Project = frappe.qb.DocType("Customer Project")
	columns = [Project.criteria]
	if frappe.db.has_column("Customer Project", "industries"):
		columns += [Project.industries, Project.company_size]
	return (
		frappe.qb.from_(Project)
		.select(*columns)
		.where(Project.user.isin(_team(customer) or [""]))
		.orderby(Project.creation, order=Order.desc)
		.run(as_dict=True)
	)


def _newest_company_size(projects: list[dict]) -> str | None:
	for project in projects:
		size = COMPANY_SIZE_VALUES.get(project.get("company_size"), project.get("company_size"))
		if size in COMPANY_SIZES:
			return size
	return None


def _newest_industries(customer: str, projects: list[dict]) -> list[str]:
	"""The company's own old industry, and the newest project's: its answer, else the
	industries its Edit criteria picked."""
	picked = [_old_column("Customer", customer, "industry")]
	for project in projects:
		criteria = frappe.parse_json(project.criteria or "{}") or {}
		answer = frappe.parse_json(project.get("industries") or "[]") or criteria.get("industries")
		if answer:
			picked += answer
			break
	return [name for name in dict.fromkeys(picked) if name and frappe.db.exists("Industry", name)]


def _requirement_company_size(customer: str) -> str | None:
	size = frappe.db.get_value(
		"Requirement", {"customer": customer}, "company_size", order_by="creation desc"
	)
	return size if size in COMPANY_SIZES else None


def _old_column(doctype: str, name: str, column: str) -> str | None:
	if not frappe.db.has_column(doctype, column):
		return None
	Table = frappe.qb.DocType(doctype)
	rows = frappe.qb.from_(Table).select(Table[column]).where(Table.name == name).run(pluck=True)
	return rows[0] if rows else None


def _team(customer: str) -> list[str]:
	return frappe.get_all("Customer Team Member", filters={"customer": customer}, pluck="user")
