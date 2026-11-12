# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from connect.customer.doctype.customer_project.project_notifications import notify_quote_update
from connect.partner.doctype.connect_partner_member.connect_partner_member import LEAD_ACCESS
from connect.permissions import _has_partner_access

# Once the customer shows interest in the partner's quote, the partner learns who they are.
REVEALING_STATUSES = ("Interested", "Hire Requested", "Hired")
# What Frappe's sales CRM shows of the brief, on its partner's note there.
FRAPPE_CRM_FIELDS = ("status", "amount", "timeline_weeks")
# A partner quotes, or changes their quote, until the customer answers it.
QUOTABLE_STATUSES = ("Awaiting", "Quoted")
MAX_WEEKS = 104
NOTE_LIMIT = 300


class ProjectQuote(Document):
	"""One partner a customer's brief went to, and where that partner stands: Awaiting until
	they quote, then Quoted, and Interested or Not Interested once the customer decides.
	The quote itself is also a Quote message in their thread, which Messaging shows.

	For the partner's sales team it is one requirement on their lead for the customer (the
	Partner Lead), which holds the stage and owner of all the customer's requirements."""

	def before_insert(self):
		if self.thread and not self.lead:
			from connect.partner.doctype.partner_lead.partner_lead import lead_for_requirement

			self.lead = lead_for_requirement(self.partner, self.thread)

	def on_update(self):
		notify_quote_update(self)
		self._reveal_customer()
		if self.status == "Hired" and self.has_value_changed("status"):
			self._win_lead()
		if self.lead and any(self.has_value_changed(field) for field in FRAPPE_CRM_FIELDS):
			from connect.crm_partner_leads import queue_partner_lead_sync

			queue_partner_lead_sync(self.lead)

	def send_quote(self, amount, weeks, note: str | None = None) -> str:
		"""The caller's quote on this brief, from the chat: posted as a Quote card in the customer's
		thread and kept on the brief. Sending again before the customer answers replaces it.
		Returns the Quote message."""
		user = frappe.session.user
		if not _has_partner_access(self.partner, user, LEAD_ACCESS):
			frappe.throw(_("Only your firm's owners and sales can send quotes."), frappe.PermissionError)
		if self.status not in QUOTABLE_STATUSES:
			frappe.throw(_("The customer has already answered this quote, so it can't change now."))

		amount, weeks, note = flt(amount), cint(weeks), (note or "").strip()
		if amount <= 0:
			frappe.throw(_("Enter an amount above 0."))
		if not 1 <= weeks <= MAX_WEEKS:
			frappe.throw(_("Enter a timeline between 1 and {0} weeks.").format(MAX_WEEKS))
		if len(note) > NOTE_LIMIT:
			frappe.throw(_("Keep the note to {0} characters.").format(NOTE_LIMIT))

		from connect.messaging.doctype.connect_thread.connect_thread import ensure_partner_member

		# Whoever quotes answers the customer's questions about it, so they join the thread.
		ensure_partner_member(self.thread, user, user)
		return post_quote(self, user, amount, weeks, note)

	def _reveal_customer(self):
		if self.thread and self.status in REVEALING_STATUSES and self.has_value_changed("status"):
			frappe.get_doc("Connect Thread", self.thread).reveal_customer()

	def _win_lead(self):
		"""The partner accepting the hire wins the lead: the customer joins their Customers."""
		from connect.partner.doctype.partner_customer.partner_customer import add_won_customer

		if self.lead:
			frappe.get_doc("Partner Lead", self.lead).win()
		add_won_customer(self)


def post_quote(quote, sender: str, amount: float, weeks: int, note: str) -> str:
	"""Posts the Quote card in the brief's thread as `sender` and records the quote on the brief.
	The demo quotes use it too, so both look the same to the customer."""
	# A card, not a typed message; send_quote checked the sender may quote for this partner.
	message = frappe.get_doc(
		{
			"doctype": "Connect Message",
			"thread": quote.thread,
			"sender": sender,
			"message_type": "Quote",
			"content": frappe.as_json(
				{"quote": quote.name, "project": quote.customer_project, "amount": amount, "weeks": weeks, "note": note}
			),
		}
	).insert(ignore_permissions=True)

	quote.update(
		{
			"amount": amount,
			"timeline_weeks": weeks,
			"note": note,
			"quote_message": message.name,
			"status": "Quoted",
			"quoted_on": now_datetime(),
		}
	)
	# Partners have no Desk write on briefs; send_quote checked this one is theirs to quote.
	quote.save(ignore_permissions=True)
	return message.name


def quotable_briefs(thread: str) -> list[dict]:
	"""The briefs in this thread the caller can quote on, oldest first: none unless they are an
	owner or in sales at the thread's partner."""
	partner = frappe.db.get_value("Connect Thread", thread, "partner")
	if not partner or not _has_partner_access(partner, frappe.session.user, LEAD_ACCESS):
		return []

	Quote = frappe.qb.DocType("Project Quote")
	Project = frappe.qb.DocType("Customer Project")
	return (
		frappe.qb.from_(Quote)
		.join(Project)
		.on(Project.name == Quote.customer_project)
		.select(
			Quote.name, Project.project_name, Quote.status, Quote.amount, Quote.timeline_weeks.as_("weeks"), Quote.note
		)
		.where((Quote.thread == thread) & Quote.status.isin(QUOTABLE_STATUSES))
		.orderby(Quote.creation)
		.run(as_dict=True)
	)
