# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_partner
from connect.partner.doctype.partner.test_my_profile import make_industries
from connect.partner.industries import partners_in_industries

GENERAL = "_Test Industry General Partner"
TEXTILE = "_Test Industry Textile Partner"
RETAIL = "_Test Industry Retail Partner"


class IntegrationTestIndustries(IntegrationTestCase):
	"""Which partners a business's industries reach, through each Industry's group."""

	def setUp(self):
		make_industries()
		for partner, industry in ((GENERAL, "Manufacturing"), (TEXTILE, "Textile Manufacturing"), (RETAIL, "Retail")):
			make_partner(partner)
			doc = frappe.get_doc("Partner", partner)
			doc.set("industries", [{"industry": industry}])
			doc.save(ignore_permissions=True)

	def test_a_specific_industry_also_reaches_partners_in_its_group(self):
		found = partners_in_industries(["Textile Manufacturing"])
		self.assertIn(TEXTILE, found)
		self.assertIn(GENERAL, found)
		self.assertNotIn(RETAIL, found)

	def test_a_group_reaches_partners_in_any_industry_under_it(self):
		found = partners_in_industries(["Manufacturing"])
		self.assertIn(TEXTILE, found)
		self.assertIn(GENERAL, found)
		self.assertNotIn(RETAIL, found)

	def test_no_industry_means_no_limit_is_applied_by_the_caller(self):
		self.assertEqual(partners_in_industries([]), set())
