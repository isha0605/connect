# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import Case, Order
from frappe.query_builder.functions import Sum
from frappe.utils import now_datetime

from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.customer.doctype.customer_project.questions import (
	check_answers,
	get_answers,
	get_changes,
	get_company,
	get_partner_criteria,
	set_answers,
)
from connect.partner.cloud_integration import queue_cloud_link
from connect.partner.performance_events import send_project_events
from connect.customer.doctype.customer_project.project_notifications import (
	notify_project_created,
	notify_project_step,
)

# What the questionnaire's verdict ("packs" / "custom", from recommend() in
# studio/connect/utils/recommendation.ts) is stored as.
VERDICTS = {"packs": "Starter Pack", "custom": "Custom"}
VERDICT_KEYS = {stored: key for key, stored in VERDICTS.items()}

# When the project reached each status.
STATUS_TIMESTAMPS = {"Shared": "shared_on", "Hired": "hired_on", "Completed": "completed_on"}

# Paying states a Starter Pack Order stays a project in (mirrors my_orders()).
PAID = ("Paid", "Partially Refunded", "Refunded")

# Quoted is a reply nobody has decided on yet, Interested has the customer's details shared,
# and Not Interested is set aside (Restore puts it back).
QUOTE_STATUSES = ("Quoted", "Interested", "Not Interested")
OPEN_QUOTE_STATUSES = ("Quoted", "Interested")
# Partners the brief went to who have no quote to show: still to answer, or not available.
INVITED_QUOTE_STATUSES = ("Awaiting", "Partner Declined")

# Why the customer chose their partner. The page's Other chip is the free-text `hire_note`.
HIRE_REASONS = ("Price", "Timeline", "Their profile", "How they replied")
HIRE_NOTE_LIMIT = 500

# The quote statuses a hire request moves through, which only hiring.py sets.
HIRE_QUOTE_STATUSES = ("Hire Requested", "Hire Declined", "Hired")

# Step 2's tasks after hiring, all optional; the page knows their labels and links.
# The project's status while its hire quote (Project Quote, which owns the hire) is in each state.
HIRE_PROJECT_STATUSES = {"Hire Requested": "Hiring", "Hired": "Hired"}
# What a freed project forgets about the hire it had.
NO_HIRE = {"status": "Shared", "partner": None, "hired_quote": None, "hire_reason": "", "hire_note": "", "hire_requested_on": None, "live_on": None}

HOSTING_TASKS = ("fc-login", "fc-code", "fc-link")


class CustomerProject(Document):
	"""A customer's project before anything is bought: what they named it, when they need
	it live, and their questionnaire answers — which decide whether we point them at a
	Starter Pack or a custom implementation. Once paid for, the Starter Pack Order is the
	project; this stays the record of how they got there."""

	def before_insert(self):
		self.user = frappe.session.user
		self.project_name = self.project_name or self._get_next_project_name()
		# Starter Packs are off, so every project is a custom implementation.
		self.verdict = self.verdict or VERDICTS["custom"]

	def validate(self):
		self._check_hire_change()
		self._stamp_status_change()

	def after_insert(self):
		notify_project_created(self)

	def on_update(self):
		notify_project_step(self)
		send_project_events(self)
		if self.status == "Hired" and self.has_value_changed("status"):
			queue_cloud_link(self)

	def follow_hire(self, quote):
		"""Called by Project Quote, which owns the hire: Hiring while `quote` waits for the
		partner's answer, Hired once they accept, and Shared again when the request ends without
		a hire (declined, cancelled or expired)."""
		if quote.status in HIRE_PROJECT_STATUSES:
			values = {"status": HIRE_PROJECT_STATUSES[quote.status], "partner": quote.partner, "hired_quote": quote.name}
			if quote.status == "Hire Requested":
				values["hire_requested_on"] = now_datetime()
		elif self.hired_quote == quote.name:
			values = NO_HIRE
		else:
			return

		self.update(values)
		self.flags.from_hire_quote = True
		# A system step of the quote's change; whoever changed the quote was checked there.
		self.save(ignore_permissions=True)

	def set_answers(self, answers: dict) -> None:
		set_answers(self, answers)

	def check_answers(self) -> None:
		check_answers(self)

	def _get_next_project_name(self) -> str:
		"""Implementation for {company}, then (2), (3) for the same user: one more than the
		highest number they have, so a deleted draft below it leaves its number unused."""
		company = frappe.db.get_value("Customer", get_customer_for_user(self.user), "customer_name")
		base = _("Implementation for {0}").format(company) if company else _("Implementation")
		taken = frappe.get_all(
			"Customer Project", filters={"user": self.user, "project_name": ["like", f"{base}%"]}, pluck="project_name"
		)
		numbers = [_project_number(base, name) for name in taken]
		highest = max(numbers, default=0)
		return f"{base} ({highest + 1})" if highest else base

	def _check_hire_change(self):
		"""Only the hire quote moves a project into or out of Hiring and Hired; a hired project
		finishing (Completed) is the project's own step."""
		if self.flags.from_hire_quote:
			return
		before = self.get_doc_before_save()
		old = before.status if before else None
		hire = HIRE_PROJECT_STATUSES.values()
		leaving_hire = old in hire and self.status not in hire and not (old == "Hired" and self.status == "Completed")
		if self.status != old and (self.status in hire or leaving_hire):
			frappe.throw(_("A project is hired through its partner's quote. Change the Project Quote instead."))

	def _stamp_status_change(self):
		# Only the first time: a declined or withdrawn hire puts the project back to Shared.
		field = STATUS_TIMESTAMPS.get(self.status)
		if field and self.has_value_changed("status") and not self.get(field):
			self.set(field, frappe.utils.now_datetime())


def get_own_project(name: str) -> CustomerProject:
	doc = frappe.get_doc("Customer Project", name)
	if doc.user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return doc


def start_project_with_partner(partner: str, project: str | None = None, answers: str | dict | None = None) -> dict:
	"""Connect on a partner's profile or card: sends one project to that one partner, as the
	customer's Requirement card in their chat. The project is an existing one of theirs
	(`project`, with any answers it lacks given here), or a new one saved from `answers`.
	Returns the project and the chat."""
	from connect.customer.doctype.customer_project.brief import send_brief
	from connect.messaging.doctype.connect_thread.connect_thread import get_or_open_thread
	from connect.partner.doctype.partner.partner import VERIFIED
	from connect.permissions import _get_partner_admins

	customer = get_customer_for_user(frappe.session.user)
	if not customer:
		frappe.throw(_("Sign in with your company account to connect with a partner."), frappe.PermissionError)
	# Only an approved partner still on Connect takes new work, and their chats go to their
	# owners: without any, nobody would read it.
	listed = frappe.db.get_value("Partner", partner, ["enabled", "verification_status"], as_dict=True)
	takes_work = listed and listed.enabled and listed.verification_status == VERIFIED
	if not takes_work or not _get_partner_admins(partner):
		frappe.throw(_("This partner can't take messages yet."))

	doc = _existing_project_to_send(project, partner) if project else frappe.new_doc("Customer Project")
	_save_answers(doc, answers)
	# The customer picked this partner themselves, so the partner sees who they are, from the
	# brief's own notifications on.
	thread = get_or_open_thread(customer, partner, doc.user)
	frappe.get_doc("Connect Thread", thread).reveal_customer()
	send_brief(doc, customer, partner)
	if doc.status == "Draft":
		doc.status = "Shared"
	doc.shared_count = (doc.shared_count or 0) + 1
	doc.save(ignore_permissions=True)
	return {"project": project_dict(doc), "thread": thread}


def _existing_project_to_send(name: str, partner: str) -> CustomerProject:
	"""The caller's project, if it can go to `partner`: still looking for one, and not sent to
	them before."""
	doc = get_own_project(name)
	if doc.status in ("Hired", "Completed"):
		frappe.throw(_("This project already has a partner."))
	if doc.status == "Hiring":
		frappe.throw(_("You've asked a partner to take this project on. Wait for their answer first."))
	if frappe.db.exists("Project Quote", {"customer_project": doc.name, "partner": partner}):
		frappe.throw(_("You've already sent this project to them. Carry on in Messages."))
	return doc


def _save_answers(doc: CustomerProject, answers: str | dict | None) -> None:
	"""Saves `answers` on the project, if given, once every question is answered."""
	if answers:
		doc.set_answers(frappe.parse_json(answers))
	doc.check_answers()
	# Only System Managers write projects; the caller owns this one (get_own_project) or makes it.
	doc.save(ignore_permissions=True)


def get_project(name: str) -> dict:
	return project_dict(get_own_project(name))


def share_requirements(answers: str | dict) -> dict:
	"""New project: saves the answers as a project and sends it to every partner they match, as
	the customer's own Requirement card. With no partner to send to, nothing is saved, so the
	customer can widen their answers and try again."""
	from connect.customer.doctype.customer_project.brief import send_to_partners
	from connect.customer.doctype.customer_project.partner_matching import get_brief_recipients

	customer = get_customer_for_user(frappe.session.user)
	if not customer:
		frappe.throw(_("Sign in with your company account to send this to partners."), frappe.PermissionError)

	doc = frappe.new_doc("Customer Project")
	doc.set_answers(frappe.parse_json(answers))
	doc.check_answers()
	if not get_brief_recipients(get_partner_criteria(doc)):
		frappe.throw(_("No partners match these answers yet. Try more regions or apps."))

	# Only System Managers write projects; this one is the caller's own.
	doc.insert(ignore_permissions=True)
	sent = send_to_partners(doc, customer)
	doc.status = "Shared"
	doc.shared_count = sent
	doc.save(ignore_permissions=True)
	return project_dict(doc)


def update_requirements(name: str, answers: str | dict) -> dict:
	"""Edit on sent requirements: saves the changed answers and sends them to every partner who
	has them. With nothing changed, sends nothing."""
	from connect.customer.doctype.customer_project.brief import send_requirements_update

	doc = get_own_project(name)
	if doc.status != "Shared":
		frappe.throw(_("Requirements can change only while you're choosing a partner."))
	customer = get_customer_for_user(doc.user)
	if not customer:
		frappe.throw(_("Sign in with your company account to send this to partners."), frappe.PermissionError)

	before = get_answers(doc)
	doc.set_answers(frappe.parse_json(answers))
	doc.check_answers()
	changes = get_changes(before, get_answers(doc))
	if not changes:
		return {**project_dict(doc), "update_sent_to": 0}

	doc.requirements_updated_on = now_datetime()
	# Only System Managers write projects; get_own_project checked the caller owns this one.
	doc.save(ignore_permissions=True)
	sent = send_requirements_update(doc, customer, changes)
	return {**project_dict(doc), "update_sent_to": sent}


def my_projects() -> list[dict]:
	"""The caller's projects, newest first, in the Projects page's row shape. Once the
	partner accepts, a row shows them like a booked pack; until then it says who it's waiting on."""
	if frappe.session.user == "Guest":
		return []
	from connect.customer.doctype.customer_project.hiring import get_hire_days_left
	from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import FRAPPE_LOGO, with_timezone

	return [
		{
			"kind": "project",
			"project": row.name,
			"project_title": row.project_name,
			"status": row.status,
			"verdict": VERDICT_KEYS.get(row.verdict, ""),
			"quotes": int(row.quotes),
			"shortlisted": int(row.shortlisted),
			"hired": row.status in ("Hired", "Completed"),
			"awaiting_partner": row.status == "Hiring",
			"hire_days_left": get_hire_days_left(row.hire_requested_on) if row.status == "Hiring" else None,
			"partner_name": (row.partner_name or row.partner) if row.partner else "Frappe",
			"partner_logo": (row.logo_icon or row.logo) if row.partner else FRAPPE_LOGO,
			"created_on": with_timezone(row.creation),
			# The brief, for the Contact dialog to show or ask for.
			"budget": row.budget,
			"description": row.description,
		}
		for row in _project_rows(frappe.session.user)
	]


def project_dict(doc: CustomerProject) -> dict:
	from connect.customer.doctype.customer_project.brief import requirement_rows
	from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import with_timezone

	company = get_company(doc)
	return {
		"name": doc.name,
		"project_name": doc.project_name,
		"status": doc.status,
		"verdict": VERDICT_KEYS.get(doc.verdict, ""),
		"regions": frappe.parse_json(doc.regions) or [],
		"company_size": company.company_size if company else "",
		"industries": company.get_industries() if company else [],
		"apps": [row.app for row in doc.apps],
		"go_live": doc.go_live,
		"work_modes": frappe.parse_json(doc.work_modes) or [],
		"operations": doc.operations,
		"systems": frappe.parse_json(doc.systems) or [],
		"problems": frappe.parse_json(doc.problems) or [],
		"criteria": get_partner_criteria(doc),
		"shared_count": doc.shared_count or 0,
		"brief_thread": first_brief_thread(doc.name),
		"shared_on": with_timezone(doc.shared_on),
		"requirements_updated_on": with_timezone(doc.requirements_updated_on),
		"requirement_rows": requirement_rows(doc, company),
		"budget": doc.budget,
		"description": doc.description,
		"created_on": with_timezone(doc.creation),
		"order": booked_order(doc.name),
		"hired": hired_partner(doc),
		"declined_hire": declined_hire(doc),
		"hire_reason": doc.hire_reason,
		"hire_reasons": list(HIRE_REASONS),
		"hire_note_limit": HIRE_NOTE_LIMIT,
		"hired_on": with_timezone(doc.hired_on),
		"live_on": with_timezone(doc.live_on),
		"completed_on": with_timezone(doc.completed_on),
		"done_tasks": frappe.parse_json(doc.done_tasks) or [],
		**quote_counts(doc.name),
	}


def first_brief_thread(project: str) -> str | None:
	"""The thread the brief was first sent in, so "View in Messages" opens the Requirement card."""
	return frappe.db.get_value(
		"Project Quote", {"customer_project": project, "thread": ["is", "set"]}, "thread", order_by="creation asc"
	)


def booked_order(project: str) -> str | None:
	"""The paid Starter Pack Order bought for this project, if any. From then on the order
	is the project: it shows the implementation steps under the project's name."""
	return frappe.db.get_value(
		"Starter Pack Order", {"customer_project": project, "payment_status": ["in", PAID]}, "name"
	)


def quote_counts(project: str) -> dict:
	from connect.customer.doctype.customer_project.brief import get_update_recipients

	statuses = frappe.get_all("Project Quote", filters={"customer_project": project}, pluck="status")
	return {
		"quotes": sum(1 for status in statuses if status in OPEN_QUOTE_STATUSES),
		"shortlisted": sum(1 for status in statuses if status == "Interested"),
		"update_recipients": len(get_update_recipients(project)),
	}


def list_quotes(name: str) -> list[dict]:
	"""The project's quotes, cheapest first, including those set aside as Not Interested, and
	the invited partners who have not quoted, listed below the quotes."""
	doc = get_own_project(name)
	Quote = frappe.qb.DocType("Project Quote")
	Partner = frappe.qb.DocType("Partner")
	rows = (
		frappe.qb.from_(Quote)
		.left_join(Partner)
		.on(Partner.name == Quote.partner)
		.select(
			Quote.name, Quote.partner, Quote.thread, Quote.status, Quote.amount, Quote.timeline_weeks, Quote.note,
			Quote.quoted_on, Quote.quoted_before_update,
			Partner.partner_name, Partner.tier, Partner.city, Partner.country, Partner.logo,
			Partner.verification_status,
		)
		.where(Quote.customer_project == doc.name)
		.where(Quote.status.isin(QUOTE_STATUSES + INVITED_QUOTE_STATUSES))
		.orderby(Quote.amount, order=Order.asc)
		.run(as_dict=True)
	)
	for row in rows:
		row.partner_name = row.partner_name or row.partner
		row.verified = row.pop("verification_status") == "Verified"
	return rows


def set_quote_status(quote: str, status: str) -> dict:
	if status not in QUOTE_STATUSES:
		frappe.throw(_("Pick Interested or Not interested."))
	row = frappe.get_doc("Project Quote", quote)
	get_own_project(row.customer_project)  # only the project's owner decides
	if row.status == "Awaiting":
		frappe.throw(_("This partner hasn't quoted yet."))
	if row.status in HIRE_QUOTE_STATUSES:
		frappe.throw(_("You have already asked this partner to take the project on."))
	row.status = status
	# Project Quote is a system DocType; get_own_project above checked this is the customer's own.
	row.save(ignore_permissions=True)
	return quote_counts(row.customer_project)


def set_hire_reason(name: str, reasons=None, note=None):
	"""Why they picked this partner ("What made you choose them?"): any of HIRE_REASONS, one
	per line, and a note for anything else. Done with nothing picked sends nothing."""
	doc = get_own_project(name)
	if not doc.partner:
		frappe.throw(_("Hire a partner first."))
	reasons = frappe.parse_json(reasons) or []
	if any(reason not in HIRE_REASONS for reason in reasons):
		frappe.throw(_("Pick a reason from the list."))
	note = (note or "").strip()
	if len(note) > HIRE_NOTE_LIMIT:
		frappe.throw(_("Keep the note under {0} characters.").format(HIRE_NOTE_LIMIT))

	doc.hire_reason = "\n".join(reason for reason in HIRE_REASONS if reason in reasons)
	doc.hire_note = note
	# Only System Managers write projects; get_own_project checked the caller owns this one.
	doc.save(ignore_permissions=True)


def complete_task(name: str, task: str) -> dict:
	doc = get_own_project(name)
	if task not in HOSTING_TASKS:
		frappe.throw(_("Unknown task."))
	if doc.status != "Hired":
		frappe.throw(_("Hire a partner first."))
	done = frappe.parse_json(doc.done_tasks) or []
	if task not in done:
		doc.db_set("done_tasks", frappe.as_json(done + [task]))
	return project_dict(doc)


def complete_project(name: str) -> dict:
	doc = get_own_project(name)
	if doc.status != "Hired":
		frappe.throw(_("Only a project with a partner can be completed."))
	# The partner says when it is built; the customer confirms. Ending it earlier would ask
	# for a review of work that hasn't been delivered.
	if not doc.live_on:
		frappe.throw(_("Your partner hasn't marked this project live yet."))
	doc.status = "Completed"
	doc.save(ignore_permissions=True)
	return project_dict(doc)


def hired_partner(doc: CustomerProject) -> dict | None:
	"""Who was hired and on what quote, for the Partner panel and step 2. `confirmed` is false
	while the partner has yet to accept. The Frappe Cloud setup link comes once Frappe Cloud
	has made it, and goes once the customer has answered it."""
	if not doc.partner:
		return None
	from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import with_timezone

	confirmed = doc.status in ("Hired", "Completed")
	waiting_for_customer = confirmed and doc.cloud_link_status == "Requested"
	Partner = frappe.qb.DocType("Partner")
	Quote = frappe.qb.DocType("Project Quote")
	rows = (
		frappe.qb.from_(Partner)
		.left_join(Quote)
		.on(Quote.name == doc.hired_quote)
		.select(Partner.partner_name, Partner.logo, Partner.logo_icon, Quote.amount, Quote.timeline_weeks, Quote.thread)
		.where(Partner.name == doc.partner)
		.run(as_dict=True)
	)
	row = rows[0] if rows else frappe._dict()
	return {
		"partner": doc.partner,
		"partner_name": row.partner_name or doc.partner,
		"logo": row.logo_icon or row.logo,
		"amount": row.amount,
		"timeline_weeks": row.timeline_weeks,
		"thread": row.thread,
		"confirmed": confirmed,
		"requested_on": with_timezone(doc.hire_requested_on),
		"referral_code": referral_code(doc.name, doc.partner),
		"cloud_link_status": doc.cloud_link_status if confirmed else None,
		# The page reads it by this name.
		"central_setup_url": doc.cloud_setup_url if waiting_for_customer else None,
		"is_reviewed": doc.status == "Completed" and is_partner_reviewed(doc),
	}


def is_partner_reviewed(doc: CustomerProject) -> bool:
	"""Whether the customer's company has reviewed the partner it hired, so a completed project
	asks for a review only until it has one."""
	customer = get_customer_for_user(doc.user)
	return bool(customer) and bool(frappe.db.exists("Partner Review", {"partner": doc.partner, "customer": customer}))


def declined_hire(doc: CustomerProject) -> dict | None:
	"""The partner who last declined this project, and why, for step 2's notice while the
	customer picks someone else."""
	if doc.status != "Shared":
		return None
	Quote = frappe.qb.DocType("Project Quote")
	Partner = frappe.qb.DocType("Partner")
	rows = (
		frappe.qb.from_(Quote)
		.left_join(Partner)
		.on(Partner.name == Quote.partner)
		.select(Quote.partner, Partner.partner_name, Quote.decline_reason, Quote.responded_on)
		.where(Quote.customer_project == doc.name)
		.where(Quote.status == "Hire Declined")
		.orderby(Quote.responded_on, order=Order.desc)
		.limit(1)
		.run(as_dict=True)
	)
	if not rows:
		return None
	row = rows[0]
	return {"partner_name": row.partner_name or row.partner, "reason": row.decline_reason}


def referral_code(project: str, partner: str) -> str:
	"""The partner's Frappe Cloud referral code for this project. Partners don't have one on
	file yet, so it's derived the way the prototype does: stable for each project and partner."""
	n = 7
	for ch in f"{partner}{project}":
		n = (n * 33 + ord(ch)) % 99999
	return f"{partner[:3].upper()}-{n:05d}"


def _project_rows(user: str) -> list[dict]:
	"""The user's projects with their hired partner and quote counts, in one query. A booked
	project is left out: it's listed once, as its order."""
	Project = frappe.qb.DocType("Customer Project")
	Partner = frappe.qb.DocType("Partner")
	Quote = frappe.qb.DocType("Project Quote")
	PackOrder = frappe.qb.DocType("Starter Pack Order")
	booked = (
		frappe.qb.from_(PackOrder)
		.select(PackOrder.customer_project)
		.where(PackOrder.payment_status.isin(PAID))
		.where(PackOrder.customer_project.isnotnull())
	)
	return (
		frappe.qb.from_(Project)
		.left_join(Partner)
		.on(Partner.name == Project.partner)
		.left_join(Quote)
		.on(Quote.customer_project == Project.name)
		.select(
			Project.name, Project.project_name, Project.status, Project.verdict, Project.partner, Project.creation,
			Project.hire_requested_on, Project.budget, Project.description,
			Partner.partner_name, Partner.logo, Partner.logo_icon,
			_count_where(Quote.status.isin(OPEN_QUOTE_STATUSES)).as_("quotes"),
			_count_where(Quote.status == "Interested").as_("shortlisted"),
		)
		.where(Project.user == user)
		.where(Project.name.notin(booked))
		.groupby(Project.name)
		.orderby(Project.creation, order=Order.desc)
		.run(as_dict=True)
	)


def _project_number(base: str, name: str) -> int:
	"""1 for the base name, n for "base (n)", 0 for any other name that only starts the same."""
	if name == base:
		return 1
	match = re.fullmatch(re.escape(base) + r" \((\d+)\)", name)
	return int(match.group(1)) if match else 0


def _count_where(condition):
	return Sum(Case().when(condition, 1).else_(0))
