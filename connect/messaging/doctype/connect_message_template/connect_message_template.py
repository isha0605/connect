# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ConnectMessageTemplate(Document):
	def update_personal(self, title=None, content=None):
		"""Edits a personal template; globals are edited via Desk's own save() instead, not this method."""
		if self.is_global:
			frappe.throw(_("Global templates can't be edited here"), frappe.PermissionError)
		if title is not None:
			self.title = title
		if content is not None:
			self.content = content
		self.save()

	def delete_personal(self):
		"""Deletes a personal template; globals are deleted via Desk's own delete() instead, not this method."""
		if self.is_global:
			frappe.throw(_("Global templates can't be deleted here"), frappe.PermissionError)
		self.delete()
