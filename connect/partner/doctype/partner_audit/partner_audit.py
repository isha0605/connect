# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

# An audit in these states has a date fixed for it.
DATED_STATUSES = ("Scheduled", "In Progress", "Completed")


class PartnerAudit(Document):
	"""An audit Frappe runs on a partner. Its non-conformances are separate records that link here."""

	def before_insert(self):
		# An audit copied from Press keeps the dates and tier it had there.
		self.requested_on = self.requested_on or today()
		self.partner_tier = self.partner_tier or frappe.db.get_value("Partner", self.partner, "tier")

	def validate(self):
		if self.is_new() and self.status == "Requested" and not self.press_name:
			self._check_proposed_date()
		if self.status in DATED_STATUSES and not self.audit_date:
			frappe.throw(_("Set the audit date before marking the audit {0}.").format(_(self.status)))
		if self.status == "Completed" and not self.conducted_by:
			frappe.throw(_("Set who conducted the audit before marking it Completed."))

	def on_update(self):
		if self.has_value_changed("conducted_by") or self.has_value_changed("audit_date"):
			self._update_non_conformances()

	def _check_proposed_date(self):
		if not self.proposed_audit_date or getdate(self.proposed_audit_date) <= getdate(today()):
			frappe.throw(_("Pick a proposed audit date after today."))

	def _update_non_conformances(self):
		"""Its non-conformances show the auditor and date fetched from the audit; keep them in step."""
		NonConformance = frappe.qb.DocType("Partner Non Conformance")
		(
			frappe.qb.update(NonConformance)
			.set(NonConformance.auditor, self.conducted_by)
			.set(NonConformance.audit_date, self.audit_date)
			.where(NonConformance.partner_audit == self.name)
			.run()
		)
