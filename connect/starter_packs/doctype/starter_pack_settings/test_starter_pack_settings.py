# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer


class IntegrationTestStarterPackSettings(IntegrationTestCase):
	"""The settings hold the payment gateway and which partner and consultant got the last
	order, so only System Managers read them. Pages get the GST rate and currency from the
	catalog."""

	def test_only_system_managers_can_read_the_settings(self):
		buyer = make_buyer("_test_sp_settings_buyer@example.com", "_Test SP Settings Co")
		for user in ("Guest", buyer):
			self.assertFalse(frappe.has_permission("Starter Pack Settings", "read", user=user))
		self.assertTrue(frappe.has_permission("Starter Pack Settings", "read", user="Administrator"))
