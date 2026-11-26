from collections.abc import Callable
from dataclasses import dataclass, field

# Read with every record: `name` ties it to Connect, `creation` orders a team's records.
SOURCE_STANDARD_FIELDS = ("name", "creation")

Converter = Callable[[object], object] | dict


@dataclass(frozen=True)
class Table:
	"""Source rows read from one field of a record, and the Connect table field they go into."""

	field: str
	mapping: "Mapping"


@dataclass(frozen=True)
class Mapping:
	"""How rows of one source DocType become values of one Connect DocType. Only the fields it
	copies, notes as files or reads by a rule are read from the source."""

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

	def get_source_fields(self) -> list[str]:
		"""The fields to read from the source: nothing else leaves the source site."""
		fields = [*self.fields, *self.files, *self.tables, *sorted(self.read_by_rules)]
		return [*SOURCE_STANDARD_FIELDS, *(name for name in fields if name not in SOURCE_STANDARD_FIELDS)]

	def _convert(self, target: str, value):
		converter = self.convert.get(target)
		if converter is None or value in (None, ""):
			return value
		if isinstance(converter, dict):
			return converter.get(value, value)
		return converter(value)
