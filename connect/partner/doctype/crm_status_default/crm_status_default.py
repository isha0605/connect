# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from connect.crm_stage_sync import lead_stages


class CRMStatusDefault(Document):
	"""The Connect stage one Frappe CRM status starts on, for every partner who connects a CRM."""

	def validate(self):
		if self.stage not in lead_stages():
			frappe.throw(_('"{0}" isn\'t a lead stage on Connect.').format(self.stage))
