# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import Case, Order
from frappe.query_builder.functions import Sum

from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.customer.doctype.customer_project.partner_matching import normalize_criteria
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

# Quoted is a reply nobody has decided on yet ("Others" on the project page), Interested is
# shortlisted, and Not Interested drops out of both lists (Undo puts it back).
QUOTE_STATUSES = ("Quoted", "Interested", "Not Interested")
OPEN_QUOTE_STATUSES = ("Quoted", "Interested")

# The quote statuses a hire request moves through, which only hiring.py sets.
HIRE_QUOTE_STATUSES = ("Hire Requested", "Hire Declined", "Hired")

# Step 2's tasks after hiring, all optional; the page knows their labels and links.
HOSTING_TASKS = ("fc-login", "fc-code", "fc-link")


class CustomerProject(Document):
	"""A customer's project before anything is bought: what they named it, when they need
	it live, and their questionnaire answers — which decide whether we point them at a
	Starter Pack or a custom implementation. Once paid for, the Starter Pack Order is the
	project; this stays the record of how they got there."""

	def before_insert(self):
		self.user = frappe.session.user

	def validate(self):
		self._stamp_status_change()

	def after_insert(self):
		notify_project_created(self)

	def on_update(self):
		notify_project_step(self)

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


def save_project(
	project_name, go_live=None, operations=None, problems=None, verdict=None, name=None, systems=None,
	industries=None, company_size=None,
) -> dict:
	"""Create a draft project, or update one when `name` is given ("Change my answers").
	Industries and company size come only from the Contact partners questions, so they're
	left alone when not given."""
	project_name = (project_name or "").strip()
	if not project_name:
		frappe.throw(_("Give the project a name."))

	doc = get_own_project(name) if name else frappe.new_doc("Customer Project")
	doc.update(
		{
			"project_name": project_name,
			"go_live": go_live or "",
			"operations": operations or "",
			"systems": _json_list(systems),
			"problems": _json_list(problems),
			"verdict": VERDICTS.get(verdict, ""),
		}
	)
	if industries is not None:
		doc.industries = _json_list(industries)
	if company_size is not None:
		doc.company_size = (company_size or "").strip()
	doc.save(ignore_permissions=True)
	return project_dict(doc)


def start_project_with_partner(
	partner, project_name, go_live=None, operations=None, problems=None, verdict=None, systems=None
) -> dict:
	"""Connect on a partner's profile or directory card: saves a new project from the New project
	answers and sends it to that one partner, as the customer's Requirement card in their chat.
	Returns the project and the chat."""
	from connect.customer.doctype.customer_project.brief import send_brief
	from connect.permissions import _get_partner_admin

	customer = get_customer_for_user(frappe.session.user)
	if not customer:
		frappe.throw(_("Sign in with your company account to connect with a partner."), frappe.PermissionError)
	# Nobody would read it: a partner's chats go to their admin.
	if not frappe.db.exists("Partner", partner) or not _get_partner_admin(partner):
		frappe.throw(_("This partner can't take messages yet."))

	doc = get_own_project(save_project(project_name, go_live, operations, problems, verdict, systems=systems)["name"])
	thread = send_brief(doc, customer, partner)
	doc.status = "Shared"
	doc.shared_count = 1
	doc.save(ignore_permissions=True)
	return {"project": project_dict(doc), "thread": thread}


def get_project(name: str) -> dict:
	return project_dict(get_own_project(name))


def share_requirements(name: str, budget=None, description=None) -> dict:
	"""Keep the custom-implementation brief on the project and send it to every partner its
	criteria match, as the customer's own Requirement card."""
	from connect.customer.doctype.customer_project.brief import send_to_partners

	budget = (budget or "").strip()
	description = (description or "").strip()
	if not budget:
		frappe.throw(_("Pick a budget range."))
	if not description:
		frappe.throw(_("Tell partners what you want built."))

	doc = get_own_project(name)
	if doc.status in ("Shared", "Hiring", "Hired", "Completed"):
		frappe.throw(_("These requirements have already been sent."))
	customer = get_customer_for_user(doc.user)
	if not customer:
		frappe.throw(_("Sign in with your company account to send this to partners."))

	doc.budget = budget
	doc.description = description
	sent = send_to_partners(doc, customer)
	if not sent:
		frappe.throw(_("No partners match these criteria yet. Try widening them."))

	doc.status = "Shared"
	doc.shared_count = sent
	doc.save(ignore_permissions=True)
	return project_dict(doc)


def save_criteria(name: str, criteria=None, go_live=None) -> dict:
	doc = get_own_project(name)
	doc.criteria = frappe.as_json(normalize_criteria(frappe.parse_json(criteria) or {}))
	if go_live is not None:
		doc.go_live = go_live
	doc.save(ignore_permissions=True)
	return project_dict(doc)


def delete_project(name: str):
	doc = get_own_project(name)
	frappe.delete_doc("Customer Project", doc.name, ignore_permissions=True)


def my_projects() -> list[dict]:
	"""The caller's draft projects, newest first, in the Projects page's row shape. Once the
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
		}
		for row in _project_rows(frappe.session.user)
	]


def project_dict(doc: CustomerProject) -> dict:
	from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import with_timezone

	return {
		"name": doc.name,
		"project_name": doc.project_name,
		"status": doc.status,
		"verdict": VERDICT_KEYS.get(doc.verdict, ""),
		"go_live": doc.go_live,
		"operations": doc.operations,
		"systems": frappe.parse_json(doc.systems) or [],
		"problems": frappe.parse_json(doc.problems) or [],
		"criteria": normalize_criteria(frappe.parse_json(doc.criteria) or {}),
		"shared_count": doc.shared_count or 0,
		"brief_thread": first_brief_thread(doc.name),
		"shared_on": with_timezone(doc.shared_on),
		"budget": doc.budget,
		"description": doc.description,
		"created_on": with_timezone(doc.creation),
		"order": booked_order(doc.name),
		"hired": hired_partner(doc),
		"declined_hire": declined_hire(doc),
		"hire_reason": doc.hire_reason,
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
	statuses = frappe.get_all("Project Quote", filters={"customer_project": project}, pluck="status")
	return {
		"quotes": sum(1 for status in statuses if status in OPEN_QUOTE_STATUSES),
		"shortlisted": sum(1 for status in statuses if status == "Interested"),
	}


def list_quotes(name: str) -> list[dict]:
	"""The project's quotes for the Interested / Others lists, cheapest first."""
	doc = get_own_project(name)
	Quote = frappe.qb.DocType("Project Quote")
	Partner = frappe.qb.DocType("Partner")
	rows = (
		frappe.qb.from_(Quote)
		.left_join(Partner)
		.on(Partner.name == Quote.partner)
		.select(
			Quote.name, Quote.partner, Quote.thread, Quote.status, Quote.amount, Quote.timeline_weeks, Quote.note,
			Partner.partner_name, Partner.tier, Partner.city, Partner.logo, Partner.verification_status,
		)
		.where(Quote.customer_project == doc.name)
		.where(Quote.status.isin(OPEN_QUOTE_STATUSES))
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
	row.db_set("status", status)
	return quote_counts(row.customer_project)


def set_hire_reason(name: str, reason=None):
	"""Why they picked this partner ("Why Tridots Tech?"). Skipping leaves it blank. The
	field's Select options reject anything that isn't one of the reasons."""
	doc = get_own_project(name)
	if not doc.partner:
		frappe.throw(_("Hire a partner first."))
	doc.hire_reason = reason or ""
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
	}


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
			Project.hire_requested_on,
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


def _count_where(condition):
	return Sum(Case().when(condition, 1).else_(0))


def _json_list(value) -> str:
	return frappe.as_json(frappe.parse_json(value) or [])
