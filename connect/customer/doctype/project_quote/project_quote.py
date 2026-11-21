# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import mimetypes

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from connect.api.attachments import _attach_file_to_message, _copy_message_attachment
from connect.customer.doctype.customer_project.project_notifications import notify_quote_update
from connect.partner.doctype.connect_partner_member.connect_partner_member import LEAD_ACCESS
from connect.partner.chat_sla import hand_chat_clock_to_quote
from connect.partner.performance_events import RequirementEvents
from connect.partner.sla import assign_answer_deadline, record_answer, withdraw_sibling_brief_clocks
from connect.permissions import _has_partner_access

# Once the customer shows interest in the partner's quote, the partner learns who they are.
REVEALING_STATUSES = ("Interested", "Hire Requested", "Hired")
# A hire request waiting for the partner's answer, and the hire itself. A project has one at most.
HIRE_STATUSES = ("Hire Requested", "Hired")
# What the CRM shows of the brief, on the partner's Lead note there.
FRAPPE_CRM_FIELDS = ("status", "amount", "timeline_weeks", "quoted_before_update")
# A partner quotes, or changes their quote, until the customer answers it.
QUOTABLE_STATUSES = ("Awaiting", "Quoted")
# A quote with a figure the customer may still take: what an edit to the requirements flags.
QUOTED_STATUSES = ("Quoted", "Interested")
# A brief the partner may still win, which keeps its lead open when they decline another.
OPEN_FOR_PARTNER_STATUSES = ("Awaiting", "Quoted", "Interested", "Hire Requested", "Hired")
DECLINED_LOST_REASON = "Not taking new clients"
MAX_WEEKS = 104
NOTE_LIMIT = 300
# A brochure opens in the customer's browser, so only types that can't run scripts there: no SVG.
BROCHURE_TYPES = ("application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif")


class ProjectQuote(Document):
	"""One partner a customer's brief went to, and where that partner stands: Awaiting until
	they quote, then Quoted, and Interested or Not Interested once the customer decides.
	Partner Declined is the partner saying no to the brief before quoting.
	The quote itself is also a Quote message in their thread, which Messaging shows.

	For the partner's sales team it is one requirement on their lead for the customer (the
	Partner Lead), which holds the stage and owner of all the customer's requirements.

	The quote owns the hire. Its project (Hiring, Hired), its lead (Won) and the partner's
	customer record follow from its status here, and nowhere else sets them."""

	def before_insert(self):
		if self.thread and not self.lead:
			from connect.partner.doctype.partner_lead.partner_lead import lead_for_requirement

			self.lead = lead_for_requirement(self.partner, self.thread)

		assign_answer_deadline(self)

	def after_insert(self):
		RequirementEvents(self).send_received()

	def validate(self):
		if self.has_value_changed("status"):
			self._check_hire_change()
			record_answer(self)
		# Set aside or hired: no longer a figure for the partner to confirm against an edit.
		if self.status not in QUOTED_STATUSES:
			self.quoted_before_update = 0

	def on_update(self):
		notify_quote_update(self)
		hand_chat_clock_to_quote(self)
		RequirementEvents(self).send_quote_steps()
		self._reveal_customer()
		if self.has_value_changed("status"):
			self._update_project_hire()
		if self.status == "Hired" and self.has_value_changed("status"):
			self._win_lead()
			withdraw_sibling_brief_clocks(self)
		if self.status == "Partner Declined" and self.has_value_changed("status"):
			self._tell_customer_of_decline()
			self._lose_lead()
		if self.lead and any(self.has_value_changed(field) for field in FRAPPE_CRM_FIELDS):
			from connect.crm_partner_leads import queue_partner_lead_sync

			queue_partner_lead_sync(self.lead)

	def send_quote(self, amount, weeks, note: str | None = None, brochure: str | None = None) -> str:
		"""The caller's quote on this brief, from the chat: posted as a Quote card in the customer's
		thread and kept on the brief. Sending again before the customer answers replaces it.
		`brochure` is the file_url of the caller's staged chat upload, or of the current quote's
		brochure to keep it. Returns the Quote message."""
		user = frappe.session.user
		if not _has_partner_access(self.partner, user, LEAD_ACCESS):
			frappe.throw(_("Only your firm's owners and sales can send quotes."), frappe.PermissionError)
		if not self.is_quotable():
			frappe.throw(_("The customer has already answered this quote, so it can't change now."))

		amount, weeks, note = flt(amount), cint(weeks), (note or "").strip()
		if amount <= 0:
			frappe.throw(_("Enter an amount above 0."))
		if not 1 <= weeks <= MAX_WEEKS:
			frappe.throw(_("Enter a timeline between 1 and {0} weeks.").format(MAX_WEEKS))
		if len(note) > NOTE_LIMIT:
			frappe.throw(_("Keep the note to {0} characters.").format(NOTE_LIMIT))
		brochure_file = self._brochure_file(brochure)

		from connect.messaging.doctype.connect_thread.connect_thread import ensure_partner_member

		# Whoever quotes answers the customer's questions about it, so they join the thread.
		ensure_partner_member(self.thread, user, user)
		return post_quote(self, user, amount, weeks, note, brochure_file)

	def _brochure_file(self, file_url: str | None):
		"""The File to post with the quote: a copy of the current quote's brochure when it is kept,
		since each Quote message owns its File, else the caller's own staged upload."""
		if not file_url:
			return None
		if self.quote_message and file_url == frappe.db.get_value("Connect Message", self.quote_message, "attachment"):
			return _copy_message_attachment(file_url)

		# The same content uploaded twice shares a file_url, so look for the caller's own upload that
		# no message has taken yet, not any File at that address.
		staged = frappe.db.get_value(
			"File", {"file_url": file_url, "owner": frappe.session.user, "attached_to_name": ["is", "not set"]}, "name"
		)
		if not staged:
			frappe.throw(_("Upload the brochure again."))
		file_doc = frappe.get_doc("File", staged)
		if mimetypes.guess_type(file_doc.file_name or "")[0] not in BROCHURE_TYPES:
			frappe.throw(_("Attach the brochure as a PDF or an image."))
		return file_doc

	def is_quotable(self) -> bool:
		"""Until the customer answers a quote, the partner can change it. After the customer edits
		their requirements, a quote made before then can change too."""
		if self.status in QUOTABLE_STATUSES:
			return True
		return bool(self.quoted_before_update and self.status == "Interested" and self._is_project_choosing())

	def confirm_quote(self):
		"""The partner's "Quote still stands" after the customer edited the requirements: the same
		figure now answers the new version."""
		if not _has_partner_access(self.partner, frappe.session.user, LEAD_ACCESS):
			frappe.throw(_("Only your firm's owners and sales can answer a brief."), frappe.PermissionError)
		if not self.quoted_before_update:
			frappe.throw(_("This quote already answers the latest requirements."))
		if self.status not in QUOTED_STATUSES or not self._is_project_choosing():
			frappe.throw(_("The customer has moved on from this quote, so it can't be confirmed now."))

		self.quoted_before_update = 0
		# Partners have no Desk write on briefs; the check above made sure this one is theirs.
		self.save(ignore_permissions=True)
		company_name = frappe.db.get_value("Partner", self.partner, "company_name") or self.partner
		frappe.get_doc("Connect Thread", self.thread).post_system_message(
			_("{0} confirmed their quote").format(company_name)
		)

	def _is_project_choosing(self) -> bool:
		return frappe.db.get_value("Customer Project", self.customer_project, "status") == "Shared"

	def decline_brief(self):
		"""The caller's "Not interested" on this brief, from the chat or the lead. It is final:
		the customer is told the partner isn't available, and can still write to them."""
		if not _has_partner_access(self.partner, frappe.session.user, LEAD_ACCESS):
			frappe.throw(_("Only your firm's owners and sales can answer a brief."), frappe.PermissionError)
		if self.status != "Awaiting":
			frappe.throw(_("This brief already has an answer, so it can't be declined now."))

		self.status = "Partner Declined"
		# Partners have no Desk write on briefs; the check above made sure this one is theirs.
		self.save(ignore_permissions=True)

	def _tell_customer_of_decline(self):
		if not self.thread:
			return
		company_name = frappe.db.get_value("Partner", self.partner, "company_name") or self.partner
		frappe.get_doc("Connect Thread", self.thread).post_system_message(
			_("{0} is not available to take on new clients right now.").format(company_name)
		)

	def _lose_lead(self):
		"""Declining the customer's only open brief loses the lead; another open one keeps it."""
		if not self.lead:
			return
		has_open_brief = frappe.db.exists(
			"Project Quote",
			{"lead": self.lead, "name": ["!=", self.name], "status": ["in", OPEN_FOR_PARTNER_STATUSES]},
		)
		if not has_open_brief:
			frappe.get_doc("Partner Lead", self.lead).lose(DECLINED_LOST_REASON)

	def _check_hire_change(self):
		"""One hire per project, and a completed project's hire is final."""
		before = self.get_doc_before_save()
		project_status = frappe.db.get_value("Customer Project", self.customer_project, "status")
		if before and before.status == "Hired" and project_status == "Completed":
			frappe.throw(_("This project is completed, so its hire can't change."))
		if self.status in HIRE_STATUSES and frappe.db.exists(
			"Project Quote",
			{"customer_project": self.customer_project, "status": ["in", HIRE_STATUSES], "name": ["!=", self.name]},
		):
			frappe.throw(_("This project already has a partner, or is waiting for one to answer."))

	def _update_project_hire(self):
		before = self.get_doc_before_save()
		was_hire = bool(before) and before.status in HIRE_STATUSES
		if self.status in HIRE_STATUSES or was_hire:
			frappe.get_doc("Customer Project", self.customer_project).follow_hire(self)

	def _reveal_customer(self):
		if self.thread and self.status in REVEALING_STATUSES and self.has_value_changed("status"):
			frappe.get_doc("Connect Thread", self.thread).reveal_customer()

	def _win_lead(self):
		"""The partner accepting the hire wins the lead: the customer joins their Customers."""
		from connect.partner.doctype.partner_customer.partner_customer import add_won_customer

		if self.lead:
			frappe.get_doc("Partner Lead", self.lead).win()
		add_won_customer(self)


def post_quote(quote, sender: str, amount: float, weeks: int, note: str, brochure=None) -> str:
	"""Posts the Quote card in the brief's thread as `sender` and records the quote on the brief.
	A brochure File goes on the card as its attachment. The demo quotes use it too, so both look
	the same to the customer."""
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
			**_brochure_fields(brochure),
		}
	).insert(ignore_permissions=True)
	if brochure:
		_attach_file_to_message(brochure.name, "Connect Message", message.name)

	quote.update(
		{
			"amount": amount,
			"timeline_weeks": weeks,
			"note": note,
			"quote_message": message.name,
			# A customer's interest stays on a quote redone after they edited the requirements.
			"status": "Interested" if quote.status == "Interested" else "Quoted",
			"quoted_on": now_datetime(),
			"quoted_before_update": 0,
		}
	)
	# Partners have no Desk write on briefs; send_quote checked this one is theirs to quote.
	quote.save(ignore_permissions=True)
	return message.name


def _brochure_fields(brochure) -> dict:
	if not brochure:
		return {}
	return {
		"attachment": brochure.file_url,
		"file_name": brochure.file_name,
		"file_type": mimetypes.guess_type(brochure.file_name or "")[0],
		"file_size": brochure.file_size,
	}


def quotable_briefs(thread: str) -> list[dict]:
	"""The briefs in this thread the caller can quote on, oldest first: none unless they are an
	owner or in sales at the thread's partner."""
	partner = frappe.db.get_value("Connect Thread", thread, "partner")
	if not partner or not _has_partner_access(partner, frappe.session.user, LEAD_ACCESS):
		return []

	Quote = frappe.qb.DocType("Project Quote")
	Project = frappe.qb.DocType("Customer Project")
	Message = frappe.qb.DocType("Connect Message")
	return (
		frappe.qb.from_(Quote)
		.join(Project)
		.on(Project.name == Quote.customer_project)
		# the current quote's brochure, so an update starts with it
		.left_join(Message)
		.on(Message.name == Quote.quote_message)
		.select(
			Quote.name, Project.project_name, Quote.status, Quote.amount, Quote.timeline_weeks.as_("weeks"), Quote.note,
			Quote.brief_message, Quote.quoted_before_update,
			Message.attachment.as_("brochure"), Message.file_name.as_("brochure_name"), Message.file_size.as_("brochure_size"),
		)
		.where(Quote.thread == thread)
		.where(
			Quote.status.isin(QUOTABLE_STATUSES)
			| ((Quote.status == "Interested") & (Quote.quoted_before_update == 1) & (Project.status == "Shared"))
		)
		.orderby(Quote.creation)
		.run(as_dict=True)
	)
