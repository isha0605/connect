# Copyright (c) 2026
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.starter_packs.doctype.starter_pack.starter_pack import get_hours_range
from connect.starter_packs.doctype.starter_pack_order.test_starter_pack_order import make_pack

IGNORE_TEST_RECORD_DEPENDENCIES = ["Starter Pack Module Section"]


class IntegrationTestStarterPack(IntegrationTestCase):
	"""The partner profile shows these hours, so only packs on sale may count."""

	def setUp(self):
		# Own packs, not the seeded catalog, so the range does not depend on what ops has set.
		frappe.db.set_value("Starter Pack", {"is_active": 1}, "is_active", 0)

	def test_hours_range_spans_active_packs_only(self):
		make_pack("_test_pack_short", 10000, 4)
		make_pack("_test_pack_long", 20000, 12)
		inactive = make_pack("_test_pack_inactive", 30000, 50)
		frappe.db.set_value("Starter Pack", inactive, "is_active", 0)

		self.assertEqual(get_hours_range(), {"min": 4, "max": 12})

	def test_no_active_pack_gives_no_range(self):
		self.assertIsNone(get_hours_range())
