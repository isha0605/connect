# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.partner.doctype.partner_tier.partner_tier import get_tier_order
from connect.patches.create_partner_tiers import TIERS
from connect.patches.create_partner_tiers import execute as create_partner_tiers


class IntegrationTestPartnerTier(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_tiers_come_highest_first_with_beginner_last(self):
		create_partner_tiers()

		order = [tier for tier in get_tier_order() if tier in TIERS]

		self.assertEqual(order, ["Gold", "Silver", "Bronze", "Emerging", "Entry", "Beginner"])

	def test_patch_keeps_a_tier_edited_in_desk(self):
		create_partner_tiers()
		frappe.db.set_value("Partner Tier", "Bronze", "certificates_required", 5)

		create_partner_tiers()

		self.assertEqual(frappe.db.get_value("Partner Tier", "Bronze", "certificates_required"), 5)

	def test_partner_needs_a_tier_that_exists(self):
		partner = frappe.get_doc(
			{"doctype": "Partner", "company_name": "_Test Tierless Partner", "tier": "Platinum", "country": "India"}
		)

		self.assertRaises(frappe.LinkValidationError, partner.insert)
