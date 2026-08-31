import frappe
from frappe.utils import get_fullname


def execute():
	"""Merges the messaging-only Connect Customer/Connect Partner identity into the marketplace's Customer/Partner doctypes."""
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

		existing_team_users = set(
			frappe.get_all("Customer Team Member", filters={"customer": customer_name}, pluck="user")
		)
		members = frappe.get_all(
			"Connect Customer Member", filters={"customer": row.name}, fields=["user", "is_admin"]
		)
		for member in members:
			if member.user in existing_team_users:
				continue
			frappe.get_doc({
				"doctype": "Customer Team Member",
				"customer": customer_name,
				"user": member.user,
				"full_name": get_fullname(member.user),
				"is_admin": member.is_admin,
			}).insert(ignore_permissions=True)

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
