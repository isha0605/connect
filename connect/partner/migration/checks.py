from dataclasses import dataclass

import frappe
from frappe.utils import (
	get_datetime,
	getdate,
	has_unsafe_url_scheme,
	split_emails,
	validate_email_address,
	validate_phone_number,
	validate_url,
)

NUMBER_TYPES = ("Int", "Float", "Currency", "Percent", "Check")
TABLE_TYPES = ("Table", "Table MultiSelect")
# Frappe's column size for a Data field that sets no length.
DATA_LENGTH = 140


@dataclass(frozen=True)
class Problem:
	"""Why one value can't be saved. `row` is the table row's position, for a value in a table."""

	field: str
	message: str
	row: int | None = None

	def __str__(self) -> str:
		return self.message


def get_problems(
	doctype: str, values: dict, is_new: bool, may_be_blank: frozenset = frozenset()
) -> list[Problem]:
	"""What stops these values from saving cleanly in Connect: a field Connect doesn't have, a value
	its field doesn't allow, a link to a missing record, a format Frappe refuses, a value too long for
	its column, or, for a new record, a required field left blank. Checked before saving, so the trial
	run lists every problem at once."""
	meta = frappe.get_meta(doctype)
	problems = []
	for fieldname, value in values.items():
		docfield = meta.get_field(fieldname)
		if not docfield:
			problems.append(Problem(fieldname, f"{doctype} has no field {fieldname}"))
		elif docfield.fieldtype in TABLE_TYPES:
			for index, row in enumerate(value or []):
				for problem in get_problems(docfield.options, row, is_new=True):
					problems.append(Problem(fieldname, problem.message, index))
		elif value not in (None, ""):
			problem = _get_value_problem(docfield, value)
			if problem:
				problems.append(Problem(fieldname, f"{doctype}.{fieldname}: {problem}"))

	if is_new:
		problems += _get_blank_required(meta, values, may_be_blank)
	return problems


def _get_value_problem(docfield, value) -> str | None:
	if docfield.fieldtype == "Select":
		options = (docfield.options or "").split("\n")
		return (
			None if str(value) in options else f"{value!r} is not one of {', '.join(filter(None, options))}"
		)
	if docfield.fieldtype == "Link":
		return None if frappe.db.exists(docfield.options, value) else f"no {docfield.options} named {value!r}"
	if docfield.fieldtype == "Data":
		return _get_data_problem(docfield, str(value))
	if docfield.fieldtype in NUMBER_TYPES:
		return _get_parse_problem(float, value, "a number")
	if docfield.fieldtype == "Date":
		return _get_parse_problem(getdate, value, "a date")
	if docfield.fieldtype == "Datetime":
		return _get_parse_problem(get_datetime, value, "a date and time")
	return None


def _get_data_problem(docfield, value: str) -> str | None:
	"""The checks Frappe runs on a Data field when it saves, without its error popup."""
	if len(value) > (docfield.length or DATA_LENGTH):
		return f"{value[:30]!r}… is longer than {docfield.length or DATA_LENGTH} characters"
	if docfield.options == "Email" and not all(
		validate_email_address(email) for email in split_emails(value)
	):
		return f"{value!r} is not an email address"
	if docfield.options == "Phone" and not validate_phone_number(value):
		return f"{value!r} is not a phone number"
	if docfield.options == "URL" and (not validate_url(value) or has_unsafe_url_scheme(value)):
		return f"{value!r} is not a web address"
	return None


def _get_parse_problem(parse, value, expected: str) -> str | None:
	try:
		parse(value)
	# Frappe's date parsers throw a ValidationError for text they can't read.
	except TypeError, ValueError, frappe.ValidationError:
		return f"{value!r} is not {expected}"
	return None


def _get_blank_required(meta, values: dict, may_be_blank: frozenset) -> list[Problem]:
	return [
		Problem(docfield.fieldname, f"{meta.name}.{docfield.fieldname} is required but blank")
		for docfield in meta.fields
		if docfield.reqd
		and docfield.fieldname not in may_be_blank
		and not docfield.default
		and values.get(docfield.fieldname) in (None, "", [])
	]
