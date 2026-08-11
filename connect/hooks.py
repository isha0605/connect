app_name = "connect"
app_title = "Connect"
app_publisher = "Isha"
app_description = "An app for connecting customers with Frappe partners"
app_email = "isha@frappe.io"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "connect",
# 		"logo": "/assets/connect/logo.png",
# 		"title": "Connect",
# 		"route": "/connect",
# 		"has_permission": "connect.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/connect/css/connect.css"
# app_include_js = "/assets/connect/js/connect.js"

# include js, css files in header of web template
# web_include_css = "/assets/connect/css/connect.css"
# web_include_js = "/assets/connect/js/connect.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "connect/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "connect/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "connect.utils.jinja_methods",
# 	"filters": "connect.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "connect.install.before_install"
# after_install = "connect.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "connect.uninstall.before_uninstall"
# after_uninstall = "connect.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "connect.utils.before_app_install"
# after_app_install = "connect.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "connect.utils.before_app_uninstall"
# after_app_uninstall = "connect.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "connect.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "connect.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"Connect Thread": "connect.connect.permissions.get_thread_permission_query_conditions",
	"Connect Thread Member": "connect.connect.permissions.get_thread_member_permission_query_conditions",
	"Connect Message": "connect.connect.permissions.get_message_permission_query_conditions",
	"Connect Message Template": "connect.connect.permissions.get_message_template_permission_query_conditions",
	"Studio Page": "connect.connect.permissions.get_studio_page_permission_query_conditions",
}

has_permission = {
	"Connect Thread": "connect.connect.permissions.has_thread_permission",
	"Connect Thread Member": "connect.connect.permissions.has_thread_member_permission",
	"Connect Message": "connect.connect.permissions.has_message_permission",
	"Connect Message Template": "connect.connect.permissions.has_message_template_permission",
	"Studio Page": "connect.connect.permissions.has_studio_page_permission",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Connect Message": {
		"after_insert": "connect.connect.notifications.notify_thread_members",
	},
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"connect.tasks.all"
# 	],
# 	"daily": [
# 		"connect.tasks.daily"
# 	],
# 	"hourly": [
# 		"connect.tasks.hourly"
# 	],
# 	"weekly": [
# 		"connect.tasks.weekly"
# 	],
# 	"monthly": [
# 		"connect.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "connect.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "connect.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "connect.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "connect.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["connect.utils.before_request"]
# after_request = ["connect.utils.after_request"]

# Job Events
# ----------
# before_job = ["connect.utils.before_job"]
# after_job = ["connect.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"connect.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

