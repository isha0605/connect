# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

# An auditor raises non-conformances while the audit runs, or when writing it up.
RAISED_ON_STATUSES = ("In Progress", "Completed")


class PartnerNonConformance(Document):
	"""A gap an audit found in how a partner works. The partner, auditor and audit date come from its audit."""

	def validate(self):
		if self.is_new() and not self.press_name:
			self._check_audit_status()
		if self.expected_closure and self.audit_date and getdate(self.expected_closure) < getdate(self.audit_date):
			frappe.throw(_("The expected closure can't be before the audit date."))
		self._set_closure()

	def _check_audit_status(self):
		status = frappe.db.get_value("Partner Audit", self.partner_audit, "status")
		if status not in RAISED_ON_STATUSES:
			frappe.throw(_("Raise non-conformances on an audit that's In Progress or Completed."))

	def _set_closure(self):
		"""Who closed it and when follow the status, so reopening one clears them."""
		if self.status == "Closed":
			self.closed_on = self.closed_on or today()
			self.closed_by = self.closed_by or frappe.session.user
		else:
			self.closed_on = None
			self.closed_by = None
