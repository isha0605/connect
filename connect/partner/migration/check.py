from collections import defaultdict

import frappe

from connect.partner.migration.files import get_files_not_copied
from connect.partner.migration.report import Report
from connect.partner.migration.run import SOURCES, get_clients, read_sources


def run() -> str:
	"""Checks a real run against what frappe.io and Press hold now. For each DocType it counts the
	records at the source and in Connect, and names each one that didn't arrive or whose Connect
	record was deleted since. It only reads. For testing; the Partner Migration form runs the same.
		bench --site <site> execute connect.partner.migration.check.run
	"""
	report = check(read_sources(get_clients()))
	written = report.write(frappe.get_site_path("private", "partner-migration"))
	print(f"Check: report in {written}")
	for line in report.lines["counts"]:
		print(f"  {line}")
	return str(written)


def check(records: dict) -> Report:
	report = Report()
	sources = [source for source in SOURCES if source in records]
	for source in sources:
		for doctype, names in source.get_expected_names(records[source]).items():
			_check_doctype(source.SOURCE, doctype, names, report)
	# Information only: Copy Files can try these again.
	for line in get_files_not_copied([source.SOURCE for source in sources]):
		report.add("files_not_copied", line)
	return report


def _check_doctype(source: str, doctype: str, names: list[str], report: Report) -> None:
	migrated = _get_migrated(source, doctype)
	missing = [name for name in names if name not in migrated]
	gone = _get_gone({name: migrated[name] for name in names if name in migrated})

	arrived = len(names) - len(missing) - len(gone)
	report.add(
		"counts",
		f"{source} {doctype}: {len(names)} at the source, {arrived} in Connect, "
		f"{len(missing)} not migrated, {len(gone)} deleted since",
	)
	for name in missing:
		report.add("missing", f"{source} {doctype} {name}")
	for name in gone:
		target_doctype, target_name = migrated[name]
		report.add("gone", f"{source} {doctype} {name} → {target_doctype} {target_name}")


def _get_migrated(source: str, doctype: str) -> dict[str, tuple[str, str]]:
	"""Each migrated record of this source DocType, and the Connect record it became."""
	records = frappe.get_all(
		"Migration Record",
		filters={"source": source, "source_doctype": doctype},
		fields=["source_name", "target_doctype", "target_name"],
	)
	return {record.source_name: (record.target_doctype, record.target_name) for record in records}


def _get_gone(migrated: dict[str, tuple[str, str]]) -> list[str]:
	"""The source records whose Connect record no longer exists, checked once per Connect DocType."""
	by_doctype = defaultdict(dict)
	for source_name, (target_doctype, target_name) in migrated.items():
		by_doctype[target_doctype][target_name] = source_name

	gone = []
	for target_doctype, targets in by_doctype.items():
		existing = set(frappe.get_all(target_doctype, filters={"name": ["in", list(targets)]}, pluck="name"))
		gone += [source_name for target_name, source_name in targets.items() if target_name not in existing]
	return gone
