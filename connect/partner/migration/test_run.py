# Copyright (c) 2026
# See license.txt

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.partner.migration import frappe_io
from connect.partner.migration.run import migrate, run

PARTNER_ID = "_Test Migrated Partner Private Limited"
OWNER = "migrated.owner@example.test"
OLD_PARTNER_ID = "_Test Old Migrated Partner LLP"
OLD_OWNER = "migrated.old.owner@example.test"


def frappe_io_partner(**values):
	return {
		"name": PARTNER_ID,
		"company_name": "_Test Migrated Partner",
		"partner_type": "Silver",
		"status": "Approved",
		"enabled": 1,
		"email": OWNER,
		"user": OWNER,
		"partner_name": "Mira Owner",
		"country": "India",
		"custom_state": "Karnataka",
		"show_in_website": 1,
		"listing_date": "2025-06-01",
		"route": "partners/india/_test-migrated",
		"custom_process_maturity_level": 3,
		"payment_currency": "INR",
		"start_date": "2025-04-01",
		"end_date": "2026-03-31",
		"logo": "/files/migrated.png",
		"industry_type": [{"name": "row-1", "industry": "Agriculture"}],
		"custom_countries_served": [{"name": "row-2", "country": "India"}],
		"skype_id": None,
		**values,
	}


def make_exports() -> dict[tuple[str, str], list[dict]]:
	return {
		("frappe.io", "Partner"): [
			frappe_io_partner(),
			frappe_io_partner(
				name=OLD_PARTNER_ID,
				company_name="_Test Old Migrated Partner",
				email=OLD_OWNER,
				user=OLD_OWNER,
				route="partners/india/_test-old-migrated",
			),
		],
	}


def make_records(exports: dict | None = None) -> dict:
	"""What reading frappe.io would give: records by source and DocType."""
	return {frappe_io: {doctype: rows for (_source, doctype), rows in (exports or make_exports()).items()}}


class TestMigration(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def migrate(self, exports=None):
		return migrate(make_records(exports))

	def test_frappe_io_partner_comes_over_under_its_id(self):
		report = self.migrate()

		self.assertFalse(report.has_problems(), dict(report.lines))
		partner = frappe.get_doc("Partner", PARTNER_ID)
		self.assertEqual(partner.company_name, "_Test Migrated Partner")
		self.assertEqual(partner.verification_status, "Verified")
		self.assertEqual(partner.frappe_io_route, "partners/india/_test-migrated")
		self.assertEqual(str(partner.listed_on), "2025-06-01")
		self.assertEqual([row.industry for row in partner.industries], ["Agriculture"])
		self.assertEqual([row.country for row in partner.served_countries], ["India"])

	def test_owner_joins_without_an_invitation(self):
		with patch("connect.auth.invitations.send_invitation") as send_invitation:
			self.migrate()

		send_invitation.assert_not_called()
		access = frappe.db.get_value(
			"Connect Partner Member", {"partner": PARTNER_ID, "user": OWNER}, "access"
		)
		self.assertEqual(access, "Owner")

	def test_nothing_is_sent_to_the_crm(self):
		with (
			patch("connect.crm_partners.frappe_crm", return_value=MagicMock()),
			patch("connect.crm_partners.is_applying_changes", return_value=True),
			patch("connect.crm_partners.is_sent", return_value=True),
			patch("connect.crm_partners._queue") as queue,
		):
			self.migrate()

		queue.assert_not_called()
		self.assertFalse(frappe.flags.in_data_migration)

	def test_file_addresses_are_noted_for_the_file_step(self):
		self.migrate()

		file_urls = frappe.db.get_value("Migration Record", "frappe.io:Partner:" + PARTNER_ID, "file_urls")
		self.assertEqual(json.loads(file_urls), {"logo": "/files/migrated.png"})
		self.assertFalse(frappe.db.get_value("Partner", PARTNER_ID, "logo"))

	def test_a_second_run_makes_no_copies(self):
		exports = make_exports()
		self.migrate(exports)
		counts = {
			doctype: frappe.db.count(doctype)
			for doctype in (
				"Partner",
				"Partner Application",
				"Partner Certificate",
				"Partner Audit",
				"Partner Non Conformance",
				"Connect Partner Member",
			)
		}

		report = self.migrate(exports)

		self.assertFalse(report.has_problems(), dict(report.lines))
		self.assertEqual({doctype: frappe.db.count(doctype) for doctype in counts}, counts)

	def test_an_unknown_field_stops_the_run_before_anything_is_saved(self):
		exports = make_exports()
		exports[("frappe.io", "Partner")] = [frappe_io_partner(introduction="We build ERPs.")]

		report = self.migrate(exports)

		self.assertEqual(report.lines["unknown_fields"], ["Partner.introduction"])
		self.assertFalse(frappe.db.exists("Partner", PARTNER_ID))

	def test_a_bad_partner_fails_alone(self):
		exports = make_exports()
		exports[("frappe.io", "Partner")].append(
			frappe_io_partner(
				name="_Test Broken Partner LLP",
				partner_type="Platinum",
				email="broken@example.test",
				user=None,
			)
		)

		report = self.migrate(exports)

		(failure,) = report.lines["failed"]
		self.assertIn("_Test Broken Partner LLP", failure)
		self.assertIn("Platinum", failure)
		self.assertFalse(frappe.db.exists("Partner", "_Test Broken Partner LLP"))
		self.assertTrue(frappe.db.exists("Partner", PARTNER_ID))

	def test_a_bad_contact_detail_is_dropped_and_the_partner_still_comes_over(self):
		exports = make_exports()
		exports[("frappe.io", "Partner")][0] = frappe_io_partner(
			phone_number="call us maybe",
			industry_type=[{"industry": "Agriculture"}, {"industry": "_Test Spaceflight"}],
		)

		report = self.migrate(exports)

		self.assertFalse(report.has_problems(), dict(report.lines))
		partner = frappe.get_doc("Partner", PARTNER_ID)
		self.assertFalse(partner.phone)
		self.assertEqual([row.industry for row in partner.industries], ["Agriculture"])
		self.assertEqual(len(report.lines["values_dropped"]), 2)

	def test_a_second_run_keeps_what_partners_edit_in_connect(self):
		self.migrate()
		frappe.db.set_value("Partner", PARTNER_ID, {"description": "Edited in Connect", "tier": "Gold"})
		exports = make_exports()
		exports[("frappe.io", "Partner")][0] = frappe_io_partner(
			description="Older frappe.io text", end_date="2027-03-31", phone_number="+91 80 1234 5678"
		)

		self.migrate(exports)

		partner = frappe.get_doc("Partner", PARTNER_ID)
		self.assertEqual((partner.description, partner.tier), ("Edited in Connect", "Gold"))
		# frappe.io still owns the contract, and a field Connect left blank is filled.
		self.assertEqual(str(partner.contract_end_date), "2027-03-31")
		self.assertEqual(partner.phone, "+91 80 1234 5678")

	def test_a_partner_deleted_in_connect_isnt_brought_back(self):
		self.migrate()
		frappe.db.delete("Partner", PARTNER_ID)

		report = self.migrate()

		self.assertFalse(frappe.db.exists("Partner", PARTNER_ID))
		self.assertIn(f"frappe.io {PARTNER_ID} → {PARTNER_ID}", report.lines["partners_deleted_in_Connect"])

	def test_frappe_staff_isnt_made_an_owner(self):
		exports = make_exports()
		exports[("frappe.io", "Partner")][1] = frappe_io_partner(
			name=OLD_PARTNER_ID, email=OLD_OWNER, user="partners@frappe.io", route="partners/india/_old"
		)

		report = self.migrate(exports)

		self.assertIn(f"{OLD_PARTNER_ID}: partners@frappe.io is Frappe staff", report.lines["owners_skipped"])
		self.assertFalse(frappe.db.exists("Connect Partner Member", {"user": "partners@frappe.io"}))

	def test_one_person_isnt_made_owner_of_two_partners(self):
		exports = make_exports()
		exports[("frappe.io", "Partner")][1] = frappe_io_partner(
			name=OLD_PARTNER_ID, email=OLD_OWNER, user=OWNER, route="partners/india/_old"
		)

		report = self.migrate(exports)

		self.assertIn(
			f"{OWNER} already owns {PARTNER_ID}, so isn't added to {OLD_PARTNER_ID}",
			report.lines["conflicts"],
		)
		self.assertFalse(
			frappe.db.exists("Connect Partner Member", {"partner": OLD_PARTNER_ID, "user": OWNER})
		)

	def test_an_automation_on_a_migrated_doctype_must_be_switched_off(self):
		frappe.get_doc(
			{
				"doctype": "Notification",
				"name": "_Test Migration Notification",
				"subject": "New partner",
				"document_type": "Partner",
				"event": "New",
				"channel": "Email",
				"enabled": 1,
			}
		).db_insert()

		report = self.migrate()

		self.assertIn(
			"Notification _Test Migration Notification acts on Partner: switch it off for the run",
			report.lines["automations_on"],
		)
		self.assertTrue(report.has_problems())

	def test_a_trial_run_saves_nothing_and_writes_a_report(self):
		with (
			patch("connect.partner.migration.run.get_clients", return_value={}),
			patch("connect.partner.migration.run.read_sources", return_value=make_records()),
			patch("builtins.print"),
		):
			written = Path(run())
		self.addCleanup(shutil.rmtree, written)

		self.assertFalse(frappe.db.exists("Partner", PARTNER_ID))
		self.assertIn("partners_created: 2", (written / "summary.txt").read_text())
		self.assertTrue((written / "source" / "frappe.io" / "Partner.json").is_file())
