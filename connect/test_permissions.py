import frappe
from frappe.tests import IntegrationTestCase

from connect.roles import CUSTOMER_ROLE

CUSTOMER = "_test_component_customer@example.com"
OTHER_COMPONENT = "_test_other_app_component"


class IntegrationTestStudioComponentPermission(IntegrationTestCase):
	"""Signed-in users can load connect's own Studio components (the sidebar), and no others."""

	def setUp(self):
		if not frappe.db.exists("User", CUSTOMER):
			frappe.get_doc(
				{"doctype": "User", "email": CUSTOMER, "first_name": "Customer", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.get_doc("User", CUSTOMER).add_roles(CUSTOMER_ROLE)

		if not frappe.db.exists("Studio Component", OTHER_COMPONENT):
			frappe.get_doc(
				{
					"doctype": "Studio Component",
					"component_id": OTHER_COMPONENT,
					"component_name": "OtherAppComponent",
					"block": "{}",
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.delete_doc("Studio Component", OTHER_COMPONENT, force=True, ignore_missing=True)

	def test_customer_reads_the_sidebar(self):
		self.assertTrue(frappe.has_permission("Studio Component", "read", "appsidebar", user=CUSTOMER))

	def test_guest_cannot_read_the_sidebar(self):
		self.assertFalse(frappe.has_permission("Studio Component", "read", "appsidebar", user="Guest"))

	def test_customer_cannot_read_another_apps_component(self):
		self.assertFalse(frappe.has_permission("Studio Component", "read", OTHER_COMPONENT, user=CUSTOMER))

	def test_customer_cannot_edit_the_sidebar(self):
		self.assertFalse(frappe.has_permission("Studio Component", "write", "appsidebar", user=CUSTOMER))

	def test_customer_lists_only_connect_components(self):
		frappe.set_user(CUSTOMER)
		names = frappe.get_list("Studio Component", pluck="name")
		self.assertIn("appsidebar", names)
		self.assertNotIn(OTHER_COMPONENT, names)
