# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from connect.partner.doctype.connect_partner_member.connect_partner_member import LEAD_ACCESS
from connect.permissions import _has_partner_access

CLOSED_STAGES = ("Won", "Lost", "Junk", "Closed")
# What Frappe's sales CRM shows of the lead, in the partner's note on the customer's Lead there.
FRAPPE_CRM_FIELDS = ("stage", "assigned_to", "probability", "lost_reason")
# A new requirement brings these back to Open. A won customer stays won.
REOPENED_STAGES = ("Lost", "Junk", "Closed")


class NotOnCRMError(frappe.ValidationError):
	pass


class PartnerLead(Document):
	"""A customer's conversation with a partner, as the partner's sales team works it. One per
	thread: each requirement (Project Quote) the customer sends in it joins this lead, as on the
	partner's CRM, where the thread is one CRM Lead."""

	def validate(self):
		self._validate_lost_reason()
		self._validate_assigned_to()

	def on_update(self):
		if any(self.has_value_changed(field) for field in FRAPPE_CRM_FIELDS):
			from connect.crm_partner_leads import queue_partner_lead_sync

			queue_partner_lead_sync(self.name)

		# Unassigning leaves the CRM Lead with whoever has it there.
		if not self.assigned_to or not self.has_value_changed("assigned_to"):
			return
		self._add_owner_to_thread()
		if not self.flags.from_crm:
			from connect.crm_lead_owner import queue_lead_owner_sync

			queue_lead_owner_sync(self.thread, self.partner)

	def reopen(self):
		"""The customer sent a new requirement: a lead they were lost on is worked again."""
		if self.stage in REOPENED_STAGES:
			self.stage = "Open"
			self._save_as_system()

	def win(self):
		"""The customer hired the partner. Only hiring wins a lead, and a won lead stays won."""
		if self.stage != "Won":
			self.stage = "Won"
			self._save_as_system()

	def _validate_lost_reason(self):
		if self.stage != "Lost":
			self.lost_reason = None
		elif not self.lost_reason:
			frappe.throw(_("Pick why the lead was lost."))

	def _validate_assigned_to(self):
		if not self.has_value_changed("assigned_to"):
			return
		crm_owner = self.crm_owner
		# Whoever Connect assigns replaces whoever the CRM had it with.
		if not self.flags.from_crm:
			self.crm_owner = None
		if not self.assigned_to:
			return
		if not _has_partner_access(self.partner, self.assigned_to, LEAD_ACCESS):
			frappe.throw(_("{0} can't take leads. Only owners and sales can.").format(self.assigned_to))
		# The CRM gave it to them, so they are on it.
		if not self.flags.from_crm:
			self._validate_owner_on_crm(crm_owner)

	def _validate_owner_on_crm(self, crm_owner: str | None):
		"""With CRM sync on, the lead's CRM Lead must go to the same person, so they need a user there."""
		from connect.crm_integration import crm_settings

		if not crm_settings(self.partner):
			return
		member = frappe.db.get_value(
			"Connect Partner Member",
			{"partner": self.partner, "user": self.assigned_to, "is_removed": 0},
			["name", "crm_user"],
			as_dict=True,
		)
		if member.crm_user:
			return
		# The CRM named this person as the Lead's owner, so that is their user there. Someone just
		# invited from the lead gets here before the queued team match links them.
		if crm_owner and crm_owner.lower() == self.assigned_to.lower():
			frappe.db.set_value("Connect Partner Member", member.name, "crm_user", crm_owner)
			return
		name = frappe.db.get_value("User", self.assigned_to, "full_name") or self.assigned_to
		frappe.throw(
			_("{0} isn't on your CRM. Create their account there, then match them in Settings → Users.").format(name),
			NotOnCRMError,
		)

	def _add_owner_to_thread(self):
		"""Whoever works the lead has to read and answer the customer."""
		from connect.messaging.doctype.connect_thread.connect_thread import ensure_partner_member

		ensure_partner_member(self.thread, self.assigned_to, frappe.session.user)

	def _save_as_system(self):
		# A system step on the customer's action; Activity reads the Version, so record it in tests too.
		self.save(ignore_permissions=True, ignore_version=False)


def lead_for_requirement(partner: str, thread: str) -> str:
	"""The lead a new requirement in this thread joins: made with the first one, opened again
	when it was lost or closed."""
	name = frappe.db.get_value("Partner Lead", {"thread": thread}, "name")
	if name:
		frappe.get_doc("Partner Lead", name).reopen()
		return name

	customer = frappe.db.get_value("Connect Thread", thread, "customer")
	# A system step on the customer sending a brief; the partner's team never makes leads.
	lead = frappe.get_doc({"doctype": "Partner Lead", "partner": partner, "customer": customer, "thread": thread})
	return lead.insert(ignore_permissions=True).name
