import frappe


def execute():
	"""Connect Thread/Connect Customer Member/Connect Partner Member used to anchor identity
	on the lean Connect Customer/Connect Partner doctypes built for messaging, while the
	marketplace/matching side (Requirement, Price Estimate, search, the wizard...) anchors on
	the richer Customer/Partner doctypes. Those never linked to each other. This patch folds
	the messaging side onto Customer/Partner (already retargeted by this same change's doctype
	JSON edits) by find-or-creating a matching Customer/Partner per company_name and repointing
	the FK columns — it does NOT delete Connect Customer/Connect Partner themselves, so it's
	safe to run more than once and safe to run on a site (e.g. a teammate's) that has real data
	in Customer/Partner already but none in Connect Customer/Connect Partner."""
	if not frappe.db.table_exists("Connect Customer") or not frappe.db.table_exists("Connect Partner"):
		return

	placeholders = []

	for row in frappe.get_all("Connect Customer", fields=["name", "company_name"]):
		customer_name = frappe.db.get_value("Customer", {"customer_name": row.company_name}, "name")
		if not customer_name:
			customer_name = frappe.get_doc({
				"doctype": "Customer",
				"customer_name": row.company_name,
			}).insert(ignore_permissions=True).name

		frappe.db.set_value(
			"Connect Customer Member", {"customer": row.name}, "customer", customer_name, update_modified=False
		)
		frappe.db.set_value(
			"Connect Thread", {"customer": row.name}, "customer", customer_name, update_modified=False
		)

	for row in frappe.get_all("Connect Partner", fields=["name", "company_name", "verification_status"]):
		partner_name = frappe.db.get_value("Partner", {"partner_name": row.company_name}, "name")
		if not partner_name:
			partner_name = frappe.get_doc({
				"doctype": "Partner",
				"partner_name": row.company_name,
				"tier": "Bronze",
				"country": "Unknown",
				"verification_status": row.verification_status,
			}).insert(ignore_permissions=True).name
			placeholders.append(partner_name)

		frappe.db.set_value(
			"Connect Partner Member", {"partner": row.name}, "partner", partner_name, update_modified=False
		)
		frappe.db.set_value(
			"Connect Thread", {"partner": row.name}, "partner", partner_name, update_modified=False
		)

	if placeholders:
		print(
			"migrate_connect_company_to_customer_partner: created Partner record(s) with "
			f"placeholder tier=Bronze/country=Unknown — review and fix by hand: {', '.join(placeholders)}"
		)
