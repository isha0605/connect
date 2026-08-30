# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ConnectMessage(Document):
	def validate(self):
		if self.message_type == "File" and not self.attachment:
			frappe.throw(_("A file message must have an attachment"))
