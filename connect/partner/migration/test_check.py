# Copyright (c) 2026
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.partner.migration.check import check
from connect.partner.migration.run import migrate
from connect.partner.migration.test_run import PARTNER_ID, frappe_io_partner, make_exports, make_records


class TestCheck(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_a_clean_run_checks_clean(self):
		records = make_records()
		migrate(records)

		report = check(records)

		self.assertFalse(report.has_problems(), dict(report.lines))
		self.assertEqual(len(report.lines["files_not_copied"]), 4)
		# The older copy of a certificate is left out on purpose, so it isn't counted as missing.
		self.assertIn(
			"Press Partner Certificate: 2 at the source, 2 in Connect, 0 not migrated, 0 deleted since",
			report.lines["counts"],
		)

	def test_a_record_that_failed_is_named(self):
		exports = make_exports()
		exports[("frappe.io", "Partner")].append(
			frappe_io_partner(
				name="_Test Broken Partner LLP", partner_type="Platinum", email="broken@example.test"
			)
		)
		records = make_records(exports)
		migrate(records)

		report = check(records)

		self.assertEqual(report.lines["missing"], ["frappe.io Partner _Test Broken Partner LLP"])

	def test_a_record_deleted_after_the_run_is_named(self):
		records = make_records()
		migrate(records)
		audit = frappe.db.get_value("Partner Audit", {"partner": PARTNER_ID})
		frappe.db.delete("Partner Non Conformance", {"partner_audit": audit})
		frappe.db.delete("Partner Audit", audit)

		report = check(records)

		self.assertEqual(
			sorted(report.lines["gone"]),
			[
				f"Press Partner Audit ADT-0001 → Partner Audit {audit}",
				f"Press Partner Non Conformance NC-0001 → Partner Non Conformance "
				f"{frappe.db.get_value('Migration Record', 'Press:Partner Non Conformance:NC-0001', 'target_name')}",
			],
		)
