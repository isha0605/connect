import frappe

# Whitelisted entry points only — the actual logic lives in connect.utils. Kept
# here as thin wrappers because the frontend calls these dotted paths
# (connect.api.account.<name>) directly, and frappe.whitelist() has to decorate
# the function actually reached by that path.


@frappe.whitelist()
def get_my_company_members():
	from connect.utils import get_my_company_members
	return get_my_company_members()


@frappe.whitelist()
def get_my_team():
	from connect.utils import get_my_team
	return get_my_team()


@frappe.whitelist()
def remove_team_member(member):
	from connect.utils import remove_team_member
	return remove_team_member(member)


@frappe.whitelist()
def add_team_member(email, role=None, password=None):
	from connect.utils import add_team_member
	return add_team_member(email, role=role, password=password)


@frappe.whitelist()
def get_my_profile():
	from connect.utils import get_my_profile
	return get_my_profile()


@frappe.whitelist()
def update_my_profile(full_name, phone=None, role=None):
	from connect.utils import update_my_profile
	return update_my_profile(full_name, phone=phone, role=role)


@frappe.whitelist()
def upload_profile_image():
	from connect.utils import upload_profile_image
	return upload_profile_image()


@frappe.whitelist(allow_guest=True)
def get_my_context():
	from connect.utils import get_my_context
	return get_my_context()
