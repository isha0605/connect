import frappe


def execute():
	"""Sign-up used to leave Guest as who made a person's User, Customer and team membership,
	since they weren't signed in yet. Records the person instead."""
	for member in frappe.get_all(
		"Customer Team Member", filters={"owner": "Guest"}, fields=["name", "user"]
	):
		set_made_by("Customer Team Member", member.name, member.user)

	for customer in frappe.get_all("Customer", filters={"owner": "Guest"}, pluck="name"):
		admins = frappe.get_all(
			"Customer Team Member",
			filters={"customer": customer, "is_removed": 0},
			fields=["user"],
			order_by="is_admin desc, creation asc",
			limit=1,
		)
		if admins:
			set_made_by("Customer", customer, admins[0].user)

	for user in frappe.get_all(
		"User", filters={"owner": "Guest", "user_type": "Website User"}, pluck="name"
	):
		set_made_by("User", user, user)


def set_made_by(doctype, name, user):
	values = {"owner": user}
	if frappe.db.get_value(doctype, name, "modified_by") == "Guest":
		values["modified_by"] = user
	frappe.db.set_value(doctype, name, values, update_modified=False)
