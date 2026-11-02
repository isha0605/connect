import frappe

# Whitelisted entry points only — the logic lives in connect.account, connect.team and
# Connect User Settings. Kept here as thin wrappers because the frontend calls these
# dotted paths (connect.api.account.<name>) directly, and frappe.whitelist() has to
# decorate the function actually reached by that path.


@frappe.whitelist()
def get_my_company_members():
	from connect.team import get_my_company_members
	return get_my_company_members()


@frappe.whitelist()
def get_my_team():
	from connect.team import get_my_team
	return get_my_team()


@frappe.whitelist()
def remove_team_member(member):
	from connect.team import remove_team_member
	return remove_team_member(member)


@frappe.whitelist()
def add_team_member(email, role=None, password=None, full_name=None, access_level=None):
	from connect.team import add_team_member
	return add_team_member(email, role=role, password=password, full_name=full_name, access_level=access_level)


@frappe.whitelist()
def set_team_member_access(member, access_level):
	from connect.team import set_team_member_access
	return set_team_member_access(member, access_level)


@frappe.whitelist()
def get_my_profile():
	from connect.account import get_my_profile
	return get_my_profile()


@frappe.whitelist()
def update_my_profile(full_name, phone=None, role=None):
	from connect.account import update_my_profile
	return update_my_profile(full_name, phone=phone, role=role)


@frappe.whitelist()
def upload_profile_image():
	from connect.account import upload_profile_image
	return upload_profile_image()


@frappe.whitelist(allow_guest=True)
def get_my_context():
	from connect.account import get_my_context
	return get_my_context()


@frappe.whitelist()
def get_unread_notification_count():
	from connect.notifications import unread_notification_count
	return unread_notification_count(frappe.session.user)


@frappe.whitelist()
def get_my_work_settings():
	from connect.messaging.doctype.connect_user_settings.connect_user_settings import get_my_settings
	return get_my_settings()


@frappe.whitelist()
def update_my_work_settings(work_start, work_end, work_days, after_hours_behavior):
	from connect.messaging.doctype.connect_user_settings.connect_user_settings import update_my_settings
	return update_my_settings(work_start, work_end, work_days, after_hours_behavior)


@frappe.whitelist()
def get_partner_work_hours(thread=None, dm_thread=None):
	from connect.messaging.doctype.connect_user_settings.connect_user_settings import get_partner_hours_for_thread
	return get_partner_hours_for_thread(thread=thread, dm_thread=dm_thread)
