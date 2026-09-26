# Copyright (c) 2026
# For license information, please see license.txt

from frappe.model.document import Document


class StarterPackModuleSection(Document):
	"""One row per heading in a pack's View details breakdown.

	Flat on purpose: Frappe only loads one level of child rows, so modules are a
	grouping key here rather than a table of their own."""

	pass
