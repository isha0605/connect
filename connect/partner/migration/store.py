import os
import traceback
from contextlib import contextmanager

import frappe
from frappe.utils import strip_html_tags

from connect.partner.doctype.migration_record.migration_record import get_record_name
from connect.partner.migration.checks import get_problems
from connect.partner.migration.mapping import Mapping
from connect.partner.migration.report import Report

_SAVEPOINT = "partner_migration"
# The outcome for a record an earlier run made that someone has since deleted in Connect.
DELETED_IN_CONNECT = "deleted in Connect"


class MigrationProblem(Exception):
	"""A record can't be saved cleanly. Its partner is rolled back and named in the report."""


def get_migrated(source: str, source_doctype: str, source_name: str) -> str | None:
	"""The Connect record an earlier run made from this source record."""
	record = get_record_name(source, source_doctype, source_name)
	return frappe.db.get_value("Migration Record", record, "target_name")


def is_deleted(doctype: str, name: str | None) -> bool:
	"""An earlier run made this record and someone deleted it in Connect since."""
	return bool(name) and not frappe.db.exists(doctype, name)


def get_existing(mapping: Mapping, source_name: str, name: str | None = None) -> str | None:
	"""The Connect record of this source record: the one an earlier run made, else the one already
	named `name`."""
	existing = get_migrated(mapping.source, mapping.source_doctype, source_name)
	if not existing and name and frappe.db.exists(mapping.target_doctype, name):
		existing = name
	return existing


def save(
	mapping: Mapping,
	source_name: str,
	values: dict,
	name: str | None = None,
	file_urls: dict | None = None,
	update_existing: bool = False,
	report: Report | None = None,
) -> tuple[str, str]:
	"""Saves one source record into Connect and returns the Connect name and what happened. A record
	migrated before, or one already named `name`, is updated when `update_existing`, else left as is.
	One deleted in Connect since is left deleted: someone removed it on purpose."""
	existing = get_existing(mapping, source_name, name)
	if is_deleted(mapping.target_doctype, existing):
		return existing, DELETED_IN_CONNECT

	label = get_label(mapping, source_name)
	try:
		if not existing:
			values = check_values(mapping, values, is_new=True, report=report, label=label)
			existing, outcome = _insert(mapping, values, name), "created"
		elif update_existing:
			values = check_values(mapping, values, is_new=False, report=report, label=label)
			existing, outcome = _update(mapping, existing, values), "updated"
		else:
			outcome = "already migrated"
	except Exception as error:
		# Names the record, as one partner's run saves many.
		raise MigrationProblem(f"{label}: {describe(error)}") from error

	remember(mapping, source_name, existing, file_urls)
	return existing, outcome


def get_label(mapping: Mapping, source_name: str) -> str:
	"""How the report names a source record, such as "Press Partner Audit ADT-0002"."""
	return f"{mapping.source} {mapping.source_doctype} {source_name}"


def describe(error: Exception) -> str:
	"""Why a save failed, in words staff can act on: Frappe's own message without its HTML, or, for a
	fault in code, the error's type and the line of Connect it came from."""
	if isinstance(error, MigrationProblem | frappe.ValidationError):
		return strip_html_tags(str(error))

	connect = f"{os.sep}connect{os.sep}"
	frames = [frame for frame in traceback.extract_tb(error.__traceback__) if connect in frame.filename]
	if not frames:
		return f"{type(error).__name__}: {error}"
	frame = frames[-1]
	where = frame.filename.rsplit(connect, 1)[-1]
	return f"{type(error).__name__} in {where}:{frame.lineno} ({frame.name}): {error}"


def remember(mapping: Mapping, source_name: str, target_name: str, file_urls: dict | None = None) -> None:
	"""Notes which Connect record a source record became, with its file addresses for the file step."""
	record = get_record_name(mapping.source, mapping.source_doctype, source_name)
	values = {
		"target_doctype": mapping.target_doctype,
		"target_name": target_name,
		# Stored as text: set_value writes a JSON field as it is given.
		"file_urls": frappe.as_json(file_urls) if file_urls else None,
	}
	if frappe.db.exists("Migration Record", record):
		frappe.db.set_value("Migration Record", record, values)
		return

	frappe.get_doc(
		{
			"doctype": "Migration Record",
			"source": mapping.source,
			"source_doctype": mapping.source_doctype,
			"source_name": source_name,
			**values,
		}
	).insert(ignore_permissions=True)  # The migration is a system job, not a user.


def check_values(
	mapping: Mapping, values: dict, is_new: bool, report: Report | None = None, label: str = ""
) -> dict:
	"""The values to save. A bad value in a field the mapping may drop is left out and listed in the
	report; any other problem raises MigrationProblem with every reason, so the record isn't saved."""
	problems = get_problems(mapping.target_doctype, values, is_new, mapping.may_be_blank)
	droppable = [problem for problem in problems if problem.field in mapping.may_drop]
	blocking = [problem for problem in problems if problem.field not in mapping.may_drop]
	if blocking or (droppable and report is None):
		raise MigrationProblem("; ".join(str(problem) for problem in blocking or droppable))

	for problem in droppable:
		report.add("values_dropped", f"{label}: {problem}")
	return _without(values, droppable)


def _without(values: dict, problems: list) -> dict:
	"""The values with each bad field, or each bad table row, left out."""
	bad_rows = {(problem.field, problem.row) for problem in problems if problem.row is not None}
	bad_fields = {problem.field for problem in problems if problem.row is None}
	kept = {}
	for field, value in values.items():
		if field in bad_fields:
			continue
		if isinstance(value, list):
			value = [row for index, row in enumerate(value) if (field, index) not in bad_rows]
		kept[field] = value
	return kept


def _insert(mapping: Mapping, values: dict, name: str | None) -> str:
	doc = frappe.get_doc({"doctype": mapping.target_doctype, **values})
	doc.docstatus = int(mapping.is_submitted)
	# Required fields the source left blank were reported by the check and allowed by the mapping.
	doc.flags.ignore_mandatory = bool(mapping.may_be_blank)
	# The migration is a system job, not a user.
	doc.insert(ignore_permissions=True, set_name=name)
	return doc.name


def _update(mapping: Mapping, name: str, values: dict) -> str:
	doc = frappe.get_doc(mapping.target_doctype, name)
	doc.update(values)
	doc.save(ignore_permissions=True)  # The migration is a system job, not a user.
	return name


@contextmanager
def each_partner(label: str, report: Report):
	"""Runs one partner's migration inside a savepoint. When anything about it fails, only that partner
	is rolled back and named in the report, and the run goes on with the next one. `label` names the
	source record the partner comes from, as get_label does."""
	frappe.db.savepoint(_SAVEPOINT)
	try:
		yield
	except Exception as error:
		# Any failure, expected or not, must cost only this partner, never the whole run.
		frappe.db.rollback(save_point=_SAVEPOINT)
		reason = describe(error)
		# A failure of the partner's own record already starts with its name.
		report.add("failed", reason if reason.startswith(f"{label}: ") else f"{label}: {reason}")
