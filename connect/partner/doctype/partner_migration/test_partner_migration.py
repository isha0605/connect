# Copyright (c) 2026, Isha and contributors
# See license.txt

from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.partner.doctype.partner_migration.partner_migration import run_step
from connect.partner.migration import frappe_io, press
from connect.partner.migration.report import Report
from connect.partner.migration.sources import SourceError
from connect.partner.migration.test_run import PARTNER_ID, frappe_io_partner, make_exports, make_records

MODULE = "connect.partner.doctype.partner_migration.partner_migration"


def make_run(**values):
	return frappe.get_doc({"doctype": "Partner Migration", **values}).insert()


def remember_a_frappe_io_partner(run):
	"""A Migration Record from an earlier frappe.io run. Any existing record can stand as its target."""
	frappe.get_doc(
		{
			"doctype": "Migration Record",
			"source": "frappe.io",
			"source_doctype": "Partner",
			"source_name": "_Test Earlier Partner LLP",
			"target_doctype": "Partner Migration",
			"target_name": run.name,
		}
	).insert(ignore_permissions=True)


def copied(*lines):
	report = Report()
	for line in lines:
		report.add("files_copied", line)
	return report


@contextmanager
def job(records=None, error=None, files=None, files_error=None):
	"""Runs a step's job against made-up sites. The job commits and rolls back the whole transaction:
	here those keep the test's data, while the savepoints each partner runs in still roll back."""
	rollback = frappe.db.rollback
	with ExitStack() as stack:
		stack.enter_context(patch.object(frappe.db, "commit"))
		full_rollback = stack.enter_context(
			patch.object(
				frappe.db,
				"rollback",
				side_effect=lambda **kwargs: kwargs.get("save_point") and rollback(**kwargs),
			)
		)
		get_clients = stack.enter_context(
			patch(f"{MODULE}.get_clients", side_effect=lambda sources: dict.fromkeys(sources))
		)
		read_sources = stack.enter_context(
			patch(f"{MODULE}.read_sources", return_value=records or make_records(), side_effect=error)
		)
		copy_files = stack.enter_context(
			patch(f"{MODULE}.copy_files", return_value=files or Report(), side_effect=files_error)
		)
		# Error Logs are saved outside the test's transaction, so none is written here.
		stack.enter_context(patch(f"{MODULE}.frappe.log_error"))
		yield MagicMock(
			full_rollback=full_rollback,
			get_clients=get_clients,
			read_sources=read_sources,
			copy_files=copy_files,
		)


@patch(f"{MODULE}.frappe.enqueue")
@patch(f"{MODULE}.get_clients")
class TestStartingSteps(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_a_trial_run_is_queued_in_the_background(self, get_clients, enqueue):
		run = make_run()

		run.start_trial_run()

		run.reload()
		self.assertEqual((run.status, run.last_step, run.run_by), ("Queued", "Trial Run", "Administrator"))
		self.assertEqual(enqueue.call_args.kwargs["step"], "Trial Run")
		self.assertEqual(enqueue.call_args.kwargs["queue"], "long")
		get_clients.assert_called_once_with((frappe_io, press))

	def test_a_missing_connection_stops_the_step_before_it_is_queued(self, get_clients, enqueue):
		get_clients.side_effect = frappe.ValidationError("Set up the frappe.io connection")
		run = make_run()

		with self.assertRaisesRegex(frappe.ValidationError, "frappe.io connection"):
			run.start_trial_run()
		enqueue.assert_not_called()
		self.assertEqual(frappe.db.get_value("Partner Migration", run.name, "status"), "Draft")

	def test_a_run_of_one_source_needs_only_its_connection(self, get_clients, enqueue):
		make_run(sources="frappe.io only").start_trial_run()

		get_clients.assert_called_once_with((frappe_io,))

	def test_press_alone_waits_until_frappe_io_is_migrated(self, get_clients, enqueue):
		run = make_run(sources="Press only")

		with self.assertRaisesRegex(frappe.ValidationError, "Migrate frappe.io first"):
			run.start_trial_run()

		remember_a_frappe_io_partner(run)
		run.start_trial_run()
		self.assertEqual(enqueue.call_args.kwargs["step"], "Trial Run")

	def test_the_migration_needs_a_clean_trial_run(self, get_clients, enqueue):
		run = make_run()
		run.db_set({"status": "Trial Done", "is_clean": 0})

		with self.assertRaisesRegex(frappe.ValidationError, "clean trial run"):
			run.start_migration()
		enqueue.assert_not_called()

	def test_files_can_be_copied_again_once_migrated(self, get_clients, enqueue):
		run = make_run()
		run.db_set("status", "Trial Done")

		with self.assertRaisesRegex(frappe.ValidationError, "can't start"):
			run.start_copy_files()

		run.db_set("status", "Migrated")
		run.start_copy_files()
		self.assertEqual(enqueue.call_args.kwargs["step"], "Copy Files")

	def test_only_one_run_at_a_time(self, get_clients, enqueue):
		make_run().db_set("status", "Running")

		with self.assertRaisesRegex(frappe.ValidationError, "still running"):
			make_run().start_trial_run()


class TestChangingSources(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_other_sources_need_a_new_trial_run(self):
		run = make_run()
		run.db_set({"status": "Trial Done", "is_clean": 1, "last_step": "Trial Run"})
		run.reload()

		run.sources = "frappe.io only"
		run.save()

		self.assertEqual((run.status, run.is_clean, run.last_step), ("Draft", 0, None))

	def test_the_sources_cant_change_after_the_migration(self):
		run = make_run()
		run.db_set("status", "Migrated")
		run.reload()

		run.sources = "Press only"
		with self.assertRaisesRegex(frappe.ValidationError, "can't change"):
			run.save()


class TestMarkingAsFailed(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_a_stuck_step_can_be_marked_as_failed(self):
		run = make_run()
		run.db_set({"status": "Running", "last_step": "Trial Run"})

		run.mark_as_failed()

		run.reload()
		self.assertEqual(run.status, "Failed")
		self.assertIn("Marked as failed by Administrator", run.error)

	def test_a_stuck_check_leaves_the_run_migrated(self):
		run = make_run()
		run.db_set({"status": "Running", "last_step": "Check"})

		run.mark_as_failed()

		self.assertEqual(frappe.db.get_value("Partner Migration", run.name, "status"), "Migrated")

	def test_only_a_running_step_can_be_marked(self):
		with self.assertRaisesRegex(frappe.ValidationError, "queued or running"):
			make_run().mark_as_failed()


class TestRunningSteps(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_a_clean_trial_run_keeps_nothing_copies_no_files_and_shows_its_results(self):
		run = make_run()

		with job() as sites:
			run_step(run.name, "Trial Run")

		sites.full_rollback.assert_called_once_with()
		sites.copy_files.assert_not_called()
		run.reload()
		self.assertEqual((run.status, run.is_clean, run.problem_count), ("Trial Done", 1, 0))
		self.assertIn("partners_created: 3", run.summary)
		self.assertTrue(run.report_file.startswith("/private/files/"))
		self.assertTrue(run.source_snapshot.startswith("/private/files/"))

	def test_a_trial_run_lists_what_to_act_on(self):
		exports = make_exports()
		exports[("frappe.io", "Partner")] = [frappe_io_partner(introduction="We build ERPs.")]
		run = make_run()

		with job(records=make_records(exports)):
			run_step(run.name, "Trial Run")

		run.reload()
		self.assertEqual((run.status, run.is_clean, run.problem_count), ("Trial Done", 0, 1))
		self.assertEqual(
			[(row.kind, row.message) for row in run.problems], [("unknown_fields", "Partner.introduction")]
		)

	def test_a_run_reads_only_its_sources(self):
		run = make_run(sources="frappe.io only")
		records = make_records()
		del records[press]

		with job(records=records) as sites:
			run_step(run.name, "Trial Run")

		sites.get_clients.assert_called_once_with((frappe_io,))
		self.assertIn("partners_created: 2", frappe.db.get_value("Partner Migration", run.name, "summary"))

	def test_a_migration_that_meets_a_new_field_saves_nothing_and_fails(self):
		exports = make_exports()
		exports[("frappe.io", "Partner")] = [frappe_io_partner(introduction="New since the trial.")]
		run = make_run()

		with job(records=make_records(exports)) as sites:
			run_step(run.name, "Migration")

		sites.full_rollback.assert_called_once_with()
		sites.copy_files.assert_not_called()
		self.assertFalse(frappe.db.exists("Partner", PARTNER_ID))
		run.reload()
		self.assertEqual(run.status, "Failed")
		self.assertIn("Run a new trial", run.error)

	def test_the_migration_keeps_its_records_and_copies_their_files(self):
		run = make_run()

		with job(files=copied(f"Partner {PARTNER_ID}: logo")) as sites:
			run_step(run.name, "Migration")

		sites.full_rollback.assert_not_called()
		self.assertEqual(list(sites.copy_files.call_args.args[0]), ["frappe.io", "Press"])
		self.assertTrue(frappe.db.exists("Partner", PARTNER_ID))
		run.reload()
		self.assertEqual((run.status, run.is_clean), ("Migrated", 1))
		self.assertIn("files_copied: 1", run.summary)

	def test_a_file_copy_that_stops_leaves_the_records_migrated(self):
		run = make_run()

		with job(files_error=RuntimeError("disk full")):
			run_step(run.name, "Migration")

		self.assertTrue(frappe.db.exists("Partner", PARTNER_ID))
		run.reload()
		self.assertEqual((run.status, run.is_clean), ("Migrated", 0))
		self.assertEqual(
			[(row.kind, row.message) for row in run.problems],
			[("files_failed", "Copying files stopped: disk full. Click Copy Files to carry on.")],
		)

	def test_a_check_after_the_migration_is_clean(self):
		run = make_run()
		with job():
			run_step(run.name, "Migration")
			run_step(run.name, "Check")

		run.reload()
		self.assertEqual((run.status, run.is_clean, run.is_checked), ("Migrated", 1, 1))
		self.assertIn("frappe.io Partner: 2 at the source, 2 in Connect", run.summary)
		# Copying is stood in for here, so every noted file is listed: information, not a problem.
		self.assertIn("files_not_copied: 4", run.summary)

	def test_a_new_migration_needs_a_new_check(self):
		run = make_run()
		run.db_set({"status": "Trial Done", "is_clean": 1, "is_checked": 1})

		with job():
			run_step(run.name, "Migration")

		self.assertEqual(frappe.db.get_value("Partner Migration", run.name, "is_checked"), 0)

	def test_copying_files_again_reads_nothing(self):
		run = make_run()
		with job():
			run_step(run.name, "Migration")

		with job(error=AssertionError("the sites are not read again"), files=copied("a file")) as sites:
			run_step(run.name, "Copy Files")

		sites.read_sources.assert_not_called()
		run.reload()
		self.assertEqual((run.status, run.is_clean), ("Migrated", 1))
		self.assertIn("files_copied: 1", run.summary)

	def test_a_site_that_cant_be_read_fails_the_step_and_says_why(self):
		run = make_run()

		with job(error=SourceError("Couldn't read Press: PermissionError")):
			run_step(run.name, "Trial Run")

		run.reload()
		self.assertEqual((run.status, run.is_clean), ("Failed", 0))
		self.assertIn("Couldn't read Press", run.error)


class TestSendingToCrm(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	@patch("connect.crm_partners.queue_all_partners")
	@patch("connect.crm_enquiries.frappe_crm", return_value=MagicMock())
	def test_partners_go_to_the_crm_after_a_clean_check(self, frappe_crm, queue_all_partners):
		run = make_run()
		run.db_set({"status": "Migrated", "last_step": "Copy Files", "is_checked": 1})

		run.send_to_frappe_crm()

		queue_all_partners.assert_called_once()
		self.assertTrue(frappe.db.get_value("Partner Migration", run.name, "crm_queued_on"))

	@patch("connect.crm_partners.queue_all_partners")
	def test_nothing_goes_to_the_crm_before_a_clean_check(self, queue_all_partners):
		run = make_run()
		run.db_set({"status": "Migrated", "last_step": "Migration", "is_clean": 1, "is_checked": 0})

		with self.assertRaisesRegex(frappe.ValidationError, "clean check"):
			run.send_to_frappe_crm()
		queue_all_partners.assert_not_called()
