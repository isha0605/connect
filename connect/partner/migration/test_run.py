# Copyright (c) 2026
# See license.txt

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.partner.migration import frappe_io, press
from connect.partner.migration.run import migrate, read_sources, run

PARTNER_ID = "_Test Migrated Partner Private Limited"
OWNER = "migrated.owner@example.test"
NEW_OWNER = "migrated.new.owner@example.test"
HOLDER = "migrated.holder@example.test"
OLD_PARTNER_ID = "_Test Old Migrated Partner LLP"
OLD_OWNER = "migrated.old.owner@example.test"
TEAM = "_test-migrated-team"
OLD_TEAM = "_test-migrated-old-team"
NEW_TEAM = "_test-migrated-new-team"
LEFT_TEAM = "_test-migrated-left-team"


def frappe_io_partner(**values):
	return {
		"name": PARTNER_ID,
		"company_name": "_Test Migrated Partner",
		"partner_type": "Silver",
		"status": "Approved",
		"enabled": 1,
		"email": OWNER,
		"partner_name": "Mira Owner",
		"country": "India",
		"custom_state": "Karnataka",
		"custom_city": "Bengaluru",
		"address": "12 MG Road, Bengaluru",
		"custom_foundation_date": "2015-01-01",
		"custom_team_size": "11-50",
		"custom_legacy_partner_type": "Gold",
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


def team(name=TEAM, **values):
	return {"name": name, "user": OWNER, "partner_email": OWNER, **values}


def onboarding(name="PONB-0001", **values):
	"""A team's application on Press, submitted and waiting for review."""
	return {
		"name": name,
		"team": NEW_TEAM,
		"docstatus": 1,
		"status": "Pending Review",
		"company_name": "_Test New Press Partner",
		"company_email": NEW_OWNER,
		"registered_country": "India",
		"registered_state": "Karnataka",
		"employee_range": "11-50",
		"submitted_on": "2025-03-01 10:00:00",
		"incorporation_certificate": "/private/files/incorporation.pdf",
		"creation": "2025-03-01 10:00:00",
		**values,
	}


def certificate(name, issue_date, **values):
	return {
		"name": name,
		"team": TEAM,
		"course": "erpnext-distribution",
		"partner_member_email": HOLDER,
		"partner_member_name": "Asha Holder",
		"issue_date": issue_date,
		"certificate_link": f"https://school.frappe.io/certificates/{name}/",
		**values,
	}


def audit(**values):
	return {
		"name": "ADT-0001",
		"partner_team": TEAM,
		"mode_of_audit": "Online",
		"status": "Completed",
		"requested_on": "2025-02-01",
		"audit_date": "2025-02-20",
		"conducted_by": "auditor.at.frappe@example.test",
		"audit_report": "/private/files/audit.pdf",
		**values,
	}


def non_conformance(name="NC-0001", **values):
	return {
		"name": name,
		"partner_team": TEAM,
		"partner_audit": "ADT-0001",
		"status": "Open",
		"department": "Sales",
		"nc_statement": "No sales playbook",
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
				route="partners/india/_test-old-migrated",
			),
		],
		("Press", "Team"): [
			team(),
			# Approved before Press kept onboarding records: its email is all that ties it to its partner.
			team(OLD_TEAM, user=OLD_OWNER, partner_email=None),
			team(NEW_TEAM, user=NEW_OWNER, partner_email=None),
		],
		("Press", "Partner Onboarding"): [onboarding()],
		("Press", "Partner Certificate"): [
			certificate("PCERT-OLD", "2024-01-10"),
			certificate("PCERT-NEW", "2025-01-10"),
			certificate("PCERT-OLD-TEAM", "2023-05-01", team=OLD_TEAM, partner_member_email=OLD_OWNER),
		],
		("Press", "Partner Audit"): [audit()],
		("Press", "Partner Non Conformance"): [non_conformance()],
	}


def make_records(exports: dict | None = None) -> dict:
	"""What reading both sites would give: records by source and DocType."""
	records = {frappe_io: {}, press: {}}
	for (source, doctype), rows in (exports or make_exports()).items():
		records[frappe_io if source == frappe_io.SOURCE else press][doctype] = rows
	return records


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
		self.assertEqual(partner.city, "Bengaluru")
		self.assertEqual(
			[(row.city, row.address) for row in partner.offices], [("Bengaluru", "12 MG Road, Bengaluru")]
		)
		self.assertEqual(str(partner.foundation_date), "2015-01-01")
		self.assertEqual((partner.team_size, partner.legacy_partner_type), ("11-50", "Gold"))

	def test_a_press_team_joins_its_frappe_io_partner_by_email(self):
		self.migrate()

		self.assertEqual(frappe.db.count("Partner", {"email": OWNER}), 1)
		self.assertEqual(
			frappe.db.get_value("Migration Record", f"Press:Team:{TEAM}", "target_name"), PARTNER_ID
		)
		self.assertEqual(frappe.db.get_value("Partner", PARTNER_ID, "tier"), "Silver")

	def test_an_old_partner_without_onboarding_gets_its_certificates(self):
		self.migrate()

		self.assertFalse(frappe.db.exists("Partner Application", {"partner": OLD_PARTNER_ID}))
		self.assertEqual(
			frappe.get_all(
				"Partner Certificate", filters={"partner": OLD_PARTNER_ID}, pluck="partner_member_email"
			),
			[OLD_OWNER],
		)

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

	def test_a_partners_certificates_audits_and_non_conformances_come_over(self):
		report = self.migrate()

		(certificate,) = frappe.get_all("Partner Certificate", filters={"partner": PARTNER_ID}, fields=["*"])
		self.assertEqual(
			(str(certificate.issue_date), certificate.school_certificate_id), ("2025-01-10", "PCERT-NEW")
		)
		self.assertIn("Certificate PCERT-OLD: an older copy", " ".join(report.lines["skipped"]))

		(audit_name,) = frappe.get_all("Partner Audit", filters={"partner": PARTNER_ID}, pluck="name")
		self.assertEqual(frappe.db.get_value("Partner Audit", audit_name, "status"), "Completed")
		self.assertEqual(
			frappe.db.get_value("Partner Non Conformance", {"partner_audit": audit_name}, "statement"),
			"No sales playbook",
		)

	def test_a_team_still_applying_becomes_a_new_partner(self):
		self.migrate()

		partner = frappe.db.get_value(
			"Partner",
			{"company_name": "_Test New Press Partner"},
			["name", "tier", "verification_status", "email"],
			as_dict=True,
		)
		self.assertEqual(
			(partner.tier, partner.verification_status, partner.email),
			("Beginner", "Pending Review", NEW_OWNER),
		)
		access = frappe.db.get_value(
			"Connect Partner Member", {"partner": partner.name, "user": NEW_OWNER}, "access"
		)
		self.assertEqual(access, "Owner")
		application = frappe.db.get_value(
			"Partner Application", {"partner": partner.name}, ["docstatus", "status"], as_dict=True
		)
		self.assertEqual((application.docstatus, application.status), (1, "Pending Review"))

	def test_a_team_whose_partner_didnt_come_over_is_unmatched_and_not_made_a_partner(self):
		exports = make_exports()
		exports[("Press", "Team")].append(team(LEFT_TEAM, user="left@example.test", partner_email=None))

		report = self.migrate(exports)

		self.assertFalse(frappe.db.exists("Partner", {"email": "left@example.test"}))
		self.assertEqual(
			report.lines["unmatched"],
			[
				f"Team {LEFT_TEAM} (left@example.test): no partner in Connect has this email, so its records "
				"weren't brought over. If its frappe.io partner failed, fix that first."
			],
		)

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
		self.assertIn("applications_already_migrated", report.lines)

	def test_a_bad_partner_fails_alone(self):
		exports = make_exports()
		exports[("frappe.io", "Partner")].append(
			frappe_io_partner(
				name="_Test Broken Partner LLP",
				partner_type="Platinum",
				email="broken@example.test",
			)
		)

		report = self.migrate(exports)

		self.assertEqual(
			report.lines["failed"],
			["frappe.io Partner _Test Broken Partner LLP: Partner.tier: no Partner Tier named 'Platinum'"],
		)
		self.assertFalse(frappe.db.exists("Partner", "_Test Broken Partner LLP"))
		self.assertTrue(frappe.db.exists("Partner", PARTNER_ID))

	def test_a_failure_names_the_record_that_failed(self):
		exports = make_exports()
		exports[("Press", "Partner Audit")].append(audit(name="ADT-0002", status="Scheduled-ish"))

		report = self.migrate(exports)

		(failure,) = report.lines["failed"]
		self.assertTrue(
			failure.startswith(
				f"Press Team {TEAM}: Press Partner Audit ADT-0002: Partner Audit.status: 'Scheduled-ish' is not one of"
			),
			failure,
		)

	def test_a_failure_gives_frappes_message_without_its_html(self):
		def validate(doc):
			frappe.throw("<b>Registered state</b> is required when the country is India.")

		with patch("connect.partner.doctype.partner.partner.Partner.validate", validate, create=True):
			report = self.migrate()

		self.assertIn(
			f"frappe.io Partner {PARTNER_ID}: Registered state is required when the country is India.",
			report.lines["failed"],
		)

	def test_a_fault_in_code_says_where_it_happened(self):
		with patch.object(frappe_io, "_get_managers", side_effect=AttributeError("no strip")):
			report = self.migrate()

		self.assertRegex(
			report.lines["failed"][0],
			r"^frappe\.io Partner .+: AttributeError in partner/migration/frappe_io\.py:\d+ "
			r"\(_migrate_partner\): no strip$",
		)

	def test_a_bad_contact_detail_is_dropped_and_the_partner_still_comes_over(self):
		exports = make_exports()
		exports[("frappe.io", "Partner")][0] = frappe_io_partner(
			phone_number="call us maybe",
			industry_type=[{"industry": "Agriculture"}, {"industry": "_Test Spaceflight"}],
			custom_team_size="Around 30",
			custom_legacy_partner_type="Platinum",
		)

		report = self.migrate(exports)

		self.assertFalse(report.has_problems(), dict(report.lines))
		partner = frappe.get_doc("Partner", PARTNER_ID)
		self.assertFalse(partner.phone)
		self.assertEqual([row.industry for row in partner.industries], ["Agriculture"])
		self.assertFalse(partner.team_size or partner.legacy_partner_type)
		self.assertEqual(len(report.lines["values_dropped"]), 4)

	def test_an_address_without_a_city_adds_no_office_and_is_listed(self):
		exports = make_exports()
		exports[("frappe.io", "Partner")][0] = frappe_io_partner(custom_city=None)

		report = self.migrate(exports)

		self.assertFalse(report.has_problems(), dict(report.lines))
		self.assertFalse(frappe.get_doc("Partner", PARTNER_ID).offices)
		self.assertEqual(
			report.lines["values_dropped"],
			[f"{PARTNER_ID}: Partner.address has no city, so no office was added"],
		)

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
		self.assertIn(f"Press {TEAM} → {PARTNER_ID}", report.lines["partners_deleted_in_Connect"])

	def test_an_audit_deleted_in_connect_isnt_brought_back(self):
		self.migrate()
		audit = frappe.db.get_value("Partner Audit", {"partner": PARTNER_ID})
		frappe.db.delete("Partner Audit", audit)

		report = self.migrate()

		self.assertFalse(frappe.db.exists("Partner Audit", {"partner": PARTNER_ID}))
		self.assertEqual(report.lines["audits_deleted_in_Connect"], [f"ADT-0001 → {audit}"])
		self.assertIn("NC-0001: its audit", report.lines["non_conformances_deleted_in_Connect"][0])

	def test_frappe_staff_isnt_made_an_owner(self):
		exports = make_exports()
		exports[("frappe.io", "Partner")][1] = frappe_io_partner(
			name=OLD_PARTNER_ID, email="partners@frappe.io", route="partners/india/_old"
		)

		report = self.migrate(exports)

		self.assertIn(f"{OLD_PARTNER_ID}: partners@frappe.io is Frappe staff", report.lines["owners_skipped"])
		self.assertFalse(frappe.db.exists("Connect Partner Member", {"user": "partners@frappe.io"}))

	def test_one_person_isnt_made_owner_of_two_partners(self):
		exports = make_exports()
		exports[("frappe.io", "Partner")][1] = frappe_io_partner(
			name=OLD_PARTNER_ID, email=OWNER, route="partners/india/_old"
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

	def test_frappe_io_alone_migrates_without_press(self):
		records = make_records()
		del records[press]

		report = migrate(records)

		self.assertFalse(report.has_problems(), dict(report.lines))
		self.assertTrue(frappe.db.exists("Partner", PARTNER_ID))
		self.assertFalse(frappe.db.exists("Partner Application", {"partner": PARTNER_ID}))

	def test_press_is_asked_for_the_teams_of_frappe_ios_partners(self):
		frappe_io_rows = {"Partner": [frappe_io_partner()]}
		with patch(
			"connect.partner.migration.run.read",
			side_effect=lambda source, *args: frappe_io_rows if source is frappe_io else {},
		) as read:
			read_sources({frappe_io: "frappe.io client", press: "Press client"})

		read.assert_called_with(press, "Press client", {OWNER})

	def test_press_alone_is_asked_for_the_teams_of_partners_migrated_from_frappe_io(self):
		self.migrate()

		with patch("connect.partner.migration.run.read", return_value={}) as read:
			read_sources({press: "Press client"})

		read.assert_called_once_with(press, "Press client", {OWNER, OLD_OWNER})

	def test_a_trial_run_saves_nothing_and_writes_a_report(self):
		with (
			patch("connect.partner.migration.run.get_clients", return_value={}),
			patch("connect.partner.migration.run.read_sources", return_value=make_records()),
			patch("builtins.print"),
		):
			written = Path(run())
		self.addCleanup(shutil.rmtree, written)

		self.assertFalse(frappe.db.exists("Partner", PARTNER_ID))
		self.assertIn("partners_created: 3", (written / "summary.txt").read_text())
		self.assertTrue((written / "source" / "frappe.io" / "Partner.json").is_file())
