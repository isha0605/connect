# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import shutil
import tempfile
from pathlib import Path

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from connect.partner.migration import frappe_io, press
from connect.partner.migration.check import check
from connect.partner.migration.files import copy_files
from connect.partner.migration.report import PROBLEM_KINDS, Report
from connect.partner.migration.run import SOURCES, get_clients, migrate, read_sources, write_snapshot

DRAFT, QUEUED, RUNNING, TRIAL_DONE, MIGRATED, FAILED = (
	"Draft",
	"Queued",
	"Running",
	"Trial Done",
	"Migrated",
	"Failed",
)
TRIAL_RUN, MIGRATION, CHECK, COPY_FILES = "Trial Run", "Migration", "Check", "Copy Files"
# The status a run is in after each step finishes.
FINISHED_STATUS = {TRIAL_RUN: TRIAL_DONE, MIGRATION: MIGRATED, CHECK: MIGRATED, COPY_FILES: MIGRATED}
# Steps that run on data already migrated: when one stops, the data is still migrated.
AFTER_MIGRATION = (CHECK, COPY_FILES)
# The sources each choice reads, in the order they migrate.
SOURCE_CHOICES = {"Both": SOURCES, "frappe.io only": (frappe_io,), "Press only": (press,)}
# Enough to act on in the form. The full report keeps every line.
PROBLEMS_SHOWN = 500
JOB_TIMEOUT_SECONDS = 2 * 60 * 60


class PartnerMigration(Document):
	"""One migration of frappe.io's and Press's partner records into Connect, from both sites or from
	one. Each step runs in the background: a trial run, the migration once a trial run is clean,
	which also copies the files, a check of what arrived, and copying the files again for any that
	failed."""

	def validate(self):
		if self.is_new() or not self.has_value_changed("sources"):
			return
		if self.status in (QUEUED, RUNNING, MIGRATED):
			frappe.throw(_("The sources can't change once the run is {0}.").format(_(self.status)))
		# Other sources need their own clean trial run before the migration may use them.
		self.status, self.last_step, self.is_clean = DRAFT, None, 0

	def get_sources(self) -> tuple:
		return SOURCE_CHOICES[self.sources]

	@frappe.whitelist()
	def start_trial_run(self):
		self._start(TRIAL_RUN, allowed=(DRAFT, TRIAL_DONE, FAILED))

	@frappe.whitelist()
	def start_migration(self):
		if not (self.status == TRIAL_DONE and self.is_clean):
			frappe.throw(_("Run the migration only after a clean trial run."))
		self._start(MIGRATION, allowed=(TRIAL_DONE,))

	@frappe.whitelist()
	def start_check(self):
		self._start(CHECK, allowed=(MIGRATED,))

	@frappe.whitelist()
	def start_copy_files(self):
		"""Copies again the files the migration couldn't, such as one a site refused."""
		self._start(COPY_FILES, allowed=(MIGRATED,))

	@frappe.whitelist()
	def mark_as_failed(self):
		"""For a step whose background job died: the run stays Running, and blocks every other run,
		until someone marks it. A step that dies keeps none of its changes, so nothing is undone here."""
		self.check_permission("write")
		if self.status not in (QUEUED, RUNNING):
			frappe.throw(_("Only a queued or running step can be marked as failed."))

		# A check or file copy that stopped leaves the migrated data as it was.
		status = MIGRATED if self.last_step in AFTER_MIGRATION else FAILED
		message = _("Marked as failed by {0}: the step stopped without finishing.").format(
			frappe.session.user
		)
		values = {"status": status, "is_clean": 0, "finished_on": now_datetime(), "error": message}
		if self.last_step == CHECK:
			values["is_checked"] = 0
		self.db_set(values)

	@frappe.whitelist()
	def send_to_frappe_crm(self):
		"""Sends every approved partner to Frappe CRM once, as the migration itself sent nothing."""
		from connect.crm_enquiries import frappe_crm
		from connect.crm_partners import queue_all_partners
		from connect.partner.doctype.partner_tier.tier_review import is_applying_changes

		self.check_permission("write")
		self._check_is_checked(_("Send partners to Frappe CRM only after a clean check."))
		if not frappe_crm():
			frappe.throw(_("Frappe CRM isn't set up in Connect."))

		queue_all_partners()
		self.db_set("crm_queued_on", now_datetime())
		if not is_applying_changes():
			frappe.msgprint(
				_(
					"Partners are queued. They go to Frappe CRM once tier and listing changes are on in Integration Settings."
				)
			)

	def _start(self, step: str, allowed: tuple[str, ...]) -> None:
		self.check_permission("write")
		if self.status not in allowed:
			frappe.throw(_("A {0} can't start while the run is {1}.").format(_(step), _(self.status)))
		# Fails here, before anything is queued, when a connection isn't set up.
		get_clients(self.get_sources())
		self._check_frappe_io_came_first()
		self._check_nothing_running()

		self.db_set(
			{
				"status": QUEUED,
				"last_step": step,
				"run_by": frappe.session.user,
				"started_on": None,
				"finished_on": None,
				"error": None,
			}
		)
		frappe.enqueue(
			"connect.partner.doctype.partner_migration.partner_migration.run_step",
			queue="long",
			timeout=JOB_TIMEOUT_SECONDS,
			enqueue_after_commit=True,
			migration=self.name,
			step=step,
		)

	def _check_is_checked(self, message: str) -> None:
		if not (self.status == MIGRATED and self.is_checked):
			frappe.throw(message)

	def _check_frappe_io_came_first(self) -> None:
		"""Press is asked for the teams of the partners migrated from frappe.io. Before those are in
		Connect, an applicant whose partner is on frappe.io would become a partner that frappe.io's
		would later duplicate."""
		if press in self.get_sources() and frappe_io not in self.get_sources():
			if not frappe.db.exists("Migration Record", {"source": frappe_io.SOURCE}):
				frappe.throw(_("Migrate frappe.io first: Press finds its partners by frappe.io's emails."))

	def _check_nothing_running(self) -> None:
		running = frappe.db.get_value(
			"Partner Migration", {"status": ["in", [QUEUED, RUNNING]], "name": ["!=", self.name]}
		)
		if running:
			frappe.throw(
				_("Partner Migration {0} is still running. Start this one when it finishes.").format(running)
			)


def run_step(migration: str, step: str) -> None:
	"""Background job: runs one step of a migration and saves what it found on the run."""
	frappe.db.set_value("Partner Migration", migration, {"status": RUNNING, "started_on": now_datetime()})
	# Committed first, so the form shows Running while the step works.
	frappe.db.commit()

	try:
		sources = frappe.get_doc("Partner Migration", migration).get_sources()
		report, records = _run(step, sources)
	except Exception:
		# A step that stops part way keeps none of its changes.
		frappe.db.rollback()
		_save_failure(migration, step)
	else:
		_save_results(migration, step, report, records)
	frappe.db.commit()


def _run(step: str, sources: tuple) -> tuple[Report, dict | None]:
	clients = get_clients(sources)
	if step == COPY_FILES:
		# The files' addresses were noted when the records were migrated: nothing is read again.
		return copy_files(_by_source_name(clients)), None

	records = read_sources(clients)
	if step == CHECK:
		return check(records), records

	report = migrate(records)
	if step == TRIAL_RUN or report.lines.get("unknown_fields"):
		# A trial run keeps nothing, and copies no files: only its report. A migration that met a
		# field the trial didn't saved nothing either.
		frappe.db.rollback()
		return report, records

	frappe.db.commit()
	report.merge(_copy_files_after_migration(clients))
	return report, records


def _copy_files_after_migration(clients: dict) -> Report:
	"""The records are saved by now, so a file copy that stops can't undo them: it is reported, and
	Copy Files carries on from where it stopped."""
	try:
		return copy_files(_by_source_name(clients))
	except Exception as error:
		frappe.db.rollback()
		frappe.log_error(title="Partner Migration: copying files stopped")
		report = Report()
		report.add("files_failed", f"Copying files stopped: {error}. Click Copy Files to carry on.")
		return report


def _by_source_name(clients: dict) -> dict:
	return {source.SOURCE: client for source, client in clients.items()}


def _save_results(migration: str, step: str, report: Report, records: dict | None) -> None:
	doc = frappe.get_doc("Partner Migration", migration)
	problems = [(kind, line) for kind in PROBLEM_KINDS for line in report.lines.get(kind, [])]
	rows = [{"kind": kind, "message": line} for kind, line in problems[:PROBLEMS_SHOWN]]
	if len(problems) > PROBLEMS_SHOWN:
		rows.append({"kind": "more", "message": f"{len(problems) - PROBLEMS_SHOWN} more in the full report"})

	counts = [f"{kind}: {count}" for kind, count in report.get_counts().items() if kind != "counts"]
	stopped = step == MIGRATION and report.lines.get("unknown_fields")
	doc.update(
		{
			# The sources gained a field since the trial run: nothing was saved, so it needs a new trial.
			"status": FAILED if stopped else FINISHED_STATUS[step],
			"is_clean": int(not problems),
			"problem_count": len(problems),
			"summary": "\n".join(counts + report.lines.get("counts", [])),
			"finished_on": now_datetime(),
			"error": _("A source has a field the trial run didn't: nothing was saved. Run a new trial.")
			if stopped
			else None,
		}
	)
	if step == CHECK:
		doc.is_checked = int(not problems)
	elif step == MIGRATION:
		# Data that changed needs checking again before files are copied or partners sent.
		doc.is_checked = 0
	doc.set("problems", rows)
	with tempfile.TemporaryDirectory() as folder:
		doc.report_file = _attach_zip(doc, "report_file", report.write(folder))
		if records is not None:
			snapshot = write_snapshot(records, Path(folder) / "source")
			doc.source_snapshot = _attach_zip(doc, "source_snapshot", snapshot)
	doc.save()


def _attach_zip(doc: PartnerMigration, fieldname: str, folder: Path) -> str:
	"""Zips `folder` and attaches it to the run as a private file."""
	content = Path(shutil.make_archive(str(folder), "zip", folder)).read_bytes()
	return (
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{doc.name}-{fieldname.replace('_', '-')}-{now_datetime():%Y%m%d-%H%M%S}.zip",
				"content": content,
				"attached_to_doctype": doc.doctype,
				"attached_to_name": doc.name,
				"attached_to_field": fieldname,
				"is_private": 1,
			}
		)
		.insert()
		.file_url
	)


def _save_failure(migration: str, step: str) -> None:
	frappe.log_error(title=f"Partner Migration {migration}: {step} failed")
	# A failed check or file copy leaves the migrated data as it was: only that step needs running again.
	status = MIGRATED if step in AFTER_MIGRATION else FAILED
	values = {"status": status, "is_clean": 0, "finished_on": now_datetime(), "error": frappe.get_traceback()}
	if step == CHECK:
		values["is_checked"] = 0
	frappe.db.set_value("Partner Migration", migration, values)
