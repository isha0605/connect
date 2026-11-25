import json
from pathlib import Path

import frappe

from connect.partner.migration import frappe_io
from connect.partner.migration.report import Report
from connect.partner.migration.sources import get_frappe_io_client, make_patient, read

SOURCES = (frappe_io,)
# What a run saves besides the mapped records: owners' members and logins, and copied files.
OTHER_SAVED_DOCTYPES = ("Connect Partner Member", "User", "File")
# Frappe features set up in Desk that act on every save. Connect's own code stays quiet during a run,
# but these don't: each would send, assign or call out once per migrated record.
AUTOMATIONS = (
	("Notification", "document_type", {"enabled": 1}),
	("Webhook", "webhook_doctype", {"enabled": 1}),
	("Assignment Rule", "document_type", {"disabled": 0}),
	("Server Script", "reference_doctype", {"disabled": 0, "script_type": "DocType Event"}),
)


def run(apply: bool = False) -> str:
	"""Reads frappe.io and migrates its partner records into Connect. For testing from the
	command line; the Partner Migration form in Desk runs the same steps.

	Without `apply` it is a trial run: it makes every change, then rolls all of it back, so the report
	shows exactly what a real run does. The report and what was read go to the site's private folder.
		bench --site <site> execute connect.partner.migration.run.run
		bench --site <site> execute connect.partner.migration.run.run --kwargs "{'apply': True}"
	"""
	records = read_sources(get_clients())
	report = migrate(records)
	if apply:
		frappe.db.commit()  # A bench command doesn't commit on its own.
	else:
		frappe.db.rollback()

	written = report.write(frappe.get_site_path("private", "partner-migration"))
	write_snapshot(records, written / "source")
	print(f"{'Migrated' if apply else 'Trial run'}: report in {written}")
	for kind, count in report.get_counts().items():
		print(f"  {kind}: {count}")
	return str(written)


def get_clients(sources: tuple = SOURCES) -> dict:
	"""A client for each of `sources`. Fails at once when a connection isn't set up in Integration Settings."""
	getters = {frappe_io: get_frappe_io_client}
	return {source: make_patient(getters[source]()) for source in sources}


def read_sources(clients: dict) -> dict:
	"""What each source site holds for the migration, read now, by source and DocType."""
	return {source: read(source, client) for source, client in clients.items()}


def migrate(records: dict) -> Report:
	"""Checks the records' fields and migrates them unless a field is unknown. Leaves committing or
	rolling back to the caller."""
	report = Report()
	_check_fields(records, report)
	_check_automations(records, report)
	if not report.lines.get("unknown_fields"):
		_migrate(records, report)
	return report


def write_snapshot(records: dict, folder: str | Path) -> Path:
	"""Writes what was read into `folder`, one JSON file per source and DocType, so a run's input can be
	looked at afterwards."""
	folder = Path(folder)
	for source, rows in records.items():
		for doctype, records_of_doctype in rows.items():
			path = folder / source.SOURCE / f"{doctype}.json"
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_text(json.dumps(records_of_doctype, indent=1, default=str), encoding="utf-8")
	return folder


def _check_fields(records: dict, report: Report) -> None:
	"""Lists every field the mappings don't account for, and every mapped field no record has."""
	for source, rows in records.items():
		for mapping in source.MAPPINGS:
			for field in sorted(mapping.get_unknown_fields(rows[mapping.source_doctype])):
				report.add("unknown_fields", field)
			for field in sorted(mapping.get_missing_fields(rows[mapping.source_doctype])):
				report.add("fields_not_in_source", field)


def _check_automations(records: dict, report: Report) -> None:
	"""Lists each Notification, Webhook, Assignment Rule and Server Script that would act on the
	records this run saves. Muting email isn't enough in Frappe: it only stops sending, so emails made
	during the run would wait in the queue and go out afterwards. Staff switch these off first."""
	saved = {mapping.target_doctype for source in records for mapping in source.MAPPINGS}
	saved |= set(OTHER_SAVED_DOCTYPES)
	for doctype, field, filters in AUTOMATIONS:
		for row in frappe.get_all(
			doctype, filters={**filters, field: ["in", sorted(saved)]}, fields=["name", field]
		):
			report.add(
				"automations_on", f"{doctype} {row.name} acts on {row[field]}: switch it off for the run"
			)


def _migrate(records: dict, report: Report) -> None:
	# Connect's controllers skip what only suits a person's own save while this is on: invitations,
	# the Frappe CRM sync, signup limits and submission checks. Not Frappe's in_import: that also skips
	# field defaults on new records, as Data Import expects the file to hold every value.
	frappe.flags.in_data_migration = True
	try:
		# In SOURCES' order, whichever sources were read.
		for source in SOURCES:
			if source in records:
				source.migrate(records[source], report)
	finally:
		frappe.flags.in_data_migration = False
