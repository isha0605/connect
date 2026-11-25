# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

from frappe.model.document import Document


def get_record_name(source: str, source_doctype: str, source_name: str) -> str:
	"""One record per source record: its name is built from the source, so a second run finds it."""
	return f"{source}:{source_doctype}:{source_name}"


class MigrationRecord(Document):
	"""Links one frappe.io or Press record to the Connect record the migration made from it."""

	def autoname(self):
		self.name = get_record_name(self.source, self.source_doctype, self.source_name)
