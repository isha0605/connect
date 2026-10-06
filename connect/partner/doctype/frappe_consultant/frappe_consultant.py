# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Max
from frappe.utils import cint


class FrappeConsultant(Document):
	"""See connect.partner.consultants. Made and switched on and off by the Frappe Consultant
	role, never by hand (in_create), so the role and this record can't disagree."""

	def validate(self):
		self.set_rotation_order()

	def set_rotation_order(self):
		"""A unique place in the turn: the end of the line unless one is given."""
		if cint(self.rotation_order) <= 0:
			Consultant = frappe.qb.DocType("Frappe Consultant")
			last = (
				frappe.qb.from_(Consultant)
				.select(Max(Consultant.rotation_order))
				.where(Consultant.name != self.name)
			).run()[0][0]
			self.rotation_order = cint(last) + 1
			return

		taken_by = frappe.db.get_value(
			"Frappe Consultant",
			{"rotation_order": self.rotation_order, "name": ["!=", self.name]},
			"full_name",
		)
		if taken_by:
			frappe.throw(
				_("Rotation Order {0} is already {1}'s. Each consultant needs their own.").format(
					self.rotation_order, frappe.bold(taken_by)
				)
			)

	def after_insert(self):
		if self.enabled:
			from connect.partner.consultants import join_frappe_team

			join_frappe_team(self.user)

	def on_update(self):
		if not self.get_doc_before_save() or not self.has_value_changed("enabled"):
			return
		from connect.partner.consultants import join_frappe_team, leave_frappe_team

		if self.enabled:
			join_frappe_team(self.user)
		else:
			leave_frappe_team(self.user)
