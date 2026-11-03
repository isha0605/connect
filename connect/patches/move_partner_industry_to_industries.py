import frappe

# The Industry list: frappe.io's success-story categories, under the groups the customer's
# industry question already uses, plus the old Partner.industry options they didn't cover.
INDUSTRY_GROUPS = {
	"Manufacturing": [
		"Automotive Manufacturing", "Chemical Manufacturing", "Discrete Manufacturing", "Electronics Manufacturing",
		"Food and Beverages", "Furniture Manufacturing", "Jewellery Manufacturing", "Medical Device Manufacturing",
		"Pharmaceutical Manufacturing", "Process Manufacturing", "Steel Manufacturing", "Textile Manufacturing",
	],
	"Services": [
		"Aviation Industry", "Education", "Finance", "Government", "Healthcare", "Hospitality", "Logistics",
		"Nonprofit", "Professional services", "Real Estate", "Rental Business", "Technology",
	],
	"Trading and Distribution": ["Distribution", "E-commerce", "Fast Moving Consumer Goods", "Retail"],
	"Others": ["Agriculture", "Engineering and Construction"],
}
# Old Partner.industry options whose name differs in the Industry list.
RENAMED = {"FinTech": "Finance", "Professional Services": "Professional services", "Other": "Others"}


def execute():
	"""Partners now pick up to six industries (Partner.industries) from the Industry list, in place of
	the single Partner.industry Select. Seeds the list and carries each partner's old industry over."""
	_seed_industries()
	_rename_in_project_criteria()
	if not frappe.db.has_column("Partner", "industry"):
		return

	for partner, industry in frappe.db.sql(
		"select name, industry from `tabPartner` where ifnull(industry, '') != ''"
	):
		industry = RENAMED.get(industry, industry)
		if not frappe.db.exists("Industry", industry):
			frappe.get_doc({"doctype": "Industry", "title": industry}).insert(ignore_permissions=True)
		if frappe.db.exists("Partner Industry", {"parent": partner, "parentfield": "industries"}):
			continue
		frappe.get_doc({
			"doctype": "Partner Industry", "parent": partner, "parenttype": "Partner", "parentfield": "industries",
			"idx": 1, "industry": industry,
		}).db_insert()


def _seed_industries():
	story_categories = frappe.get_all(
		"Partner Success Story", filters={"category": ["is", "set"]}, pluck="category", distinct=True
	)
	grouped = {member: group for group, members in INDUSTRY_GROUPS.items() for member in members}
	names = list(INDUSTRY_GROUPS) + list(grouped) + [c.strip() for c in story_categories if c.strip()]
	for name in dict.fromkeys(names):
		if not frappe.db.exists("Industry", name):
			frappe.get_doc({"doctype": "Industry", "title": name, "industry_group": grouped.get(name)}).insert(
				ignore_permissions=True
			)


def _rename_in_project_criteria():
	"""A project's Edit criteria saved the old industry names, which now match no partner."""
	for name, criteria in frappe.get_all("Customer Project", fields=["name", "criteria"], as_list=True):
		parsed = frappe.parse_json(criteria or "{}") or {}
		industries = parsed.get("industries") or []
		renamed = list(dict.fromkeys(RENAMED.get(industry, industry) for industry in industries))
		if renamed != industries:
			parsed["industries"] = renamed
			frappe.db.set_value("Customer Project", name, "criteria", frappe.as_json(parsed), update_modified=False)
