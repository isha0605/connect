from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

# Fields every Frappe record has. Connect sets its own, so they are never copied.
STANDARD_FIELDS = frozenset(
	{
		"name",
		"owner",
		"creation",
		"modified",
		"modified_by",
		"docstatus",
		"idx",
		"doctype",
		"parent",
		"parentfield",
		"parenttype",
		"_user_tags",
		"_comments",
		"_assign",
		"_liked_by",
		"_seen",
	}
)

Converter = Callable[[object], object] | dict


@dataclass(frozen=True)
class Table:
	"""A source child table and the Connect table field its rows go into."""

	field: str
	mapping: "Mapping"


@dataclass(frozen=True)
class Mapping:
	"""How rows of one source DocType become values of one Connect DocType.

	Every source field must be copied, noted as a file, read by a rule, or skipped on purpose. Any
	other field a source record has is reported as unknown and stops the run, so nothing is lost silently.
	"""

	source: str
	source_doctype: str
	target_doctype: str
	# Source field -> Connect field.
	fields: dict[str, str] = field(default_factory=dict)
	# Connect field -> a dict of source value to Connect value, or a function of the source value.
	convert: dict[str, Converter] = field(default_factory=dict)
	# Source file field -> Connect field. Only the address is noted; the file step copies the file.
	files: dict[str, str] = field(default_factory=dict)
	# Source table field -> the Connect table its rows go into.
	tables: dict[str, Table] = field(default_factory=dict)
	read_by_rules: frozenset[str] = frozenset()
	skipped: frozenset[str] = frozenset()
	# Required Connect fields an old source record may have left blank, as the source didn't require them.
	may_be_blank: frozenset[str] = frozenset()
	# Optional Connect fields whose bad value is dropped and listed, instead of failing the record.
	# For a table, only the bad rows are dropped.
	may_drop: frozenset[str] = frozenset()
	# Records go into Connect submitted, as the source holds them.
	is_submitted: bool = False

	def get_values(self, row: dict) -> dict:
		"""The Connect values of a source row. A field the source didn't send is left out, so it
		never blanks a value Connect already has."""
		values = {
			target: self._convert(target, row[source])
			for source, target in self.fields.items()
			if source in row
		}
		for source, table in self.tables.items():
			if source in row:
				values[table.field] = [table.mapping.get_values(child) for child in row[source] or []]
		return values

	def get_file_urls(self, row: dict) -> dict[str, str]:
		return {target: row[source] for source, target in self.files.items() if row.get(source)}

	def get_unknown_fields(self, rows: Iterable[dict]) -> set[str]:
		"""Fields the source records have that this mapping doesn't account for, as "DocType.field"."""
		rows = list(rows)
		known = STANDARD_FIELDS | set(self.fields) | set(self.files) | set(self.tables)
		known |= self.read_by_rules | self.skipped
		unknown = {f"{self.source_doctype}.{name}" for row in rows for name in row if name not in known}
		for source, table in self.tables.items():
			children = [child for row in rows for child in row.get(source) or []]
			unknown |= table.mapping.get_unknown_fields(children)
		return unknown

	def get_missing_fields(self, rows: Iterable[dict]) -> set[str]:
		"""Mapped fields that no source record has: a wrong guess at a field name, or a field the
		source doesn't send."""
		rows = list(rows)
		if not rows:
			return set()

		expected = set(self.fields) | set(self.files) | set(self.tables) | self.read_by_rules
		present = {name for row in rows for name in row}
		return {f"{self.source_doctype}.{name}" for name in expected - present}

	def _convert(self, target: str, value):
		converter = self.convert.get(target)
		if converter is None or value in (None, ""):
			return value
		if isinstance(converter, dict):
			return converter.get(value, value)
		return converter(value)
