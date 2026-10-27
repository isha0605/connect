# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import math

import frappe
from frappe import _
from frappe.utils import add_days, cint, escape_html, get_url, now_datetime

from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.customer.doctype.customer_project.customer_project import (
	OPEN_QUOTE_STATUSES,
	get_own_project,
	project_dict,
)
from connect.partner.cloud_integration import queue_cloud_link
from connect.permissions import _check_can_read, _get_partner_admin, _is_partner_admin

# A request the partner hasn't answered by then is withdrawn, so the customer can hire someone else.
HIRE_REQUEST_EXPIRY_DAYS = 7


def hire_partner(quote: str) -> dict:
	"""Ask the partner behind a quote to take the project on. The project waits in Hiring until
	the partner accepts or declines, the customer cancels, or the request expires."""
	row = frappe.get_doc("Project Quote", quote)
	doc = get_own_project(row.customer_project)
	if doc.status != "Shared":
		frappe.throw(_("This project already has a partner."))
	if row.status not in OPEN_QUOTE_STATUSES:
		frappe.throw(_("Only a partner who has quoted can be hired."))

	row.update({"status_before_hire": row.status, "status": "Hire Requested", "decline_reason": None})
	row.save(ignore_permissions=True)
	doc.update(
		{
			"status": "Hiring",
			"partner": row.partner,
			"hired_quote": row.name,
			"hire_requested_on": now_datetime(),
		}
	)
	doc.save(ignore_permissions=True)

	_post_hire_request(doc, row)
	_email_partner_admin(doc, row)
	return project_dict(doc)


def respond_to_hire(quote: str, accept, reason: str | None = None) -> dict:
	"""The partner's answer to a hire request. Accepting makes them the project's partner.
	Declining needs a reason, frees the project, and the customer sees why."""
	row = frappe.get_doc("Project Quote", quote)
	if not _is_partner_admin(row.partner, frappe.session.user):
		frappe.throw(_("Only the partner's admin can answer a hire request."), frappe.PermissionError)
	if row.status != "Hire Requested":
		frappe.throw(_("This hire request has already been answered or withdrawn."))

	doc = frappe.get_doc("Customer Project", row.customer_project)
	if cint(accept):
		_accept(doc, row)
	else:
		_decline(doc, row, (reason or "").strip())
	return {"quote": row.name, "status": row.status}


def cancel_hire_request(name: str) -> dict:
	"""The customer takes back a hire request the partner hasn't answered yet."""
	doc = get_own_project(name)
	if doc.status != "Hiring":
		frappe.throw(_("There's no hire request waiting for an answer."))

	partner_name = _partner_name(doc.partner)
	_withdraw(doc, _("The hire request for {0} was cancelled.").format(doc.project_name))
	return {"partner_name": partner_name, **project_dict(doc)}


def hire_request_statuses(thread: str) -> dict:
	"""Where each hire request card in a thread stands, by message: its quote's status, the
	reason when the partner declined, and whether the caller can still answer it. A customer
	can ask the same partner again after cancelling, so only the newest card for a quote
	follows it; the older ones were withdrawn."""
	user = frappe.session.user
	_check_can_read(thread, user)
	quotes = {
		row.name: row
		for row in frappe.get_all(
			"Project Quote",
			filters={"thread": thread},
			fields=["name", "partner", "status", "decline_reason"],
		)
	}
	cards = frappe.get_all(
		"Connect Message",
		filters={"thread": thread, "message_type": "Hire Request"},
		fields=["name", "content"],
		order_by="creation desc",
	)

	statuses, seen = {}, set()
	for card in cards:
		quote = quotes.get((frappe.parse_json(card.content) or {}).get("quote"))
		if not quote or quote.name in seen:
			statuses[card.name] = {"status": "Withdrawn", "decline_reason": None, "can_answer": False}
			continue
		seen.add(quote.name)
		statuses[card.name] = {
			"status": quote.status,
			"decline_reason": quote.decline_reason,
			"can_answer": quote.status == "Hire Requested" and _is_partner_admin(quote.partner, user),
		}
	return statuses


def expire_hire_requests() -> None:
	"""Daily: withdraws the hire requests nobody answered in time."""
	cutoff = add_days(now_datetime(), -HIRE_REQUEST_EXPIRY_DAYS)
	for name in frappe.get_all(
		"Customer Project", filters={"status": "Hiring", "hire_requested_on": ["<", cutoff]}, pluck="name"
	):
		try:
			doc = frappe.get_doc("Customer Project", name)
			_withdraw(
				doc,
				_("{0} didn't answer the hire request for {1} within {2} days, so it was withdrawn.").format(
					_partner_name(doc.partner), doc.project_name, HIRE_REQUEST_EXPIRY_DAYS
				),
			)
			frappe.db.commit()  # nosemgrep: one project's failure shouldn't undo the others
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Could not expire the hire request for {name}")


def get_hire_days_left(requested_on) -> int:
	"""Whole days until an unanswered hire request expires. Never below 1: the daily
	expiry job can leave a request open for a few hours past its deadline."""
	remaining = add_days(requested_on, HIRE_REQUEST_EXPIRY_DAYS) - now_datetime()
	return max(1, math.ceil(remaining.total_seconds() / 86400))


def _accept(doc, row):
	row.update({"status": "Hired", "responded_on": now_datetime()})
	row.save(ignore_permissions=True)
	doc.status = "Hired"
	doc.save(ignore_permissions=True)
	queue_cloud_link(doc)
	_post_system_message(
		row.thread,
		_("{0} accepted the hire for {1}.").format(_partner_name(row.partner), doc.project_name),
	)


def _decline(doc, row, reason: str):
	if not reason:
		frappe.throw(_("Tell the customer why you're declining."))

	row.update({"status": "Hire Declined", "responded_on": now_datetime(), "decline_reason": reason})
	row.save(ignore_permissions=True)
	_free_project(doc)
	_post_system_message(
		row.thread,
		_("{0} declined the hire for {1}: {2}").format(_partner_name(row.partner), doc.project_name, reason),
	)


def _withdraw(doc, message: str):
	"""Puts the quote back where it was before the request, and the project back to Shared."""
	row = frappe.get_doc("Project Quote", doc.hired_quote)
	row.update({"status": row.status_before_hire or "Quoted", "status_before_hire": None})
	row.save(ignore_permissions=True)
	_free_project(doc)
	_post_system_message(row.thread, message)


def _free_project(doc):
	doc.update(
		{
			"status": "Shared",
			"partner": None,
			"hired_quote": None,
			"hire_reason": "",
			"hire_requested_on": None,
		}
	)
	doc.save(ignore_permissions=True)


def _post_hire_request(doc, row):
	"""The request as a card in the customer's thread with the partner, where the partner answers it."""
	frappe.get_doc(
		{
			"doctype": "Connect Message",
			"thread": row.thread,
			"sender": frappe.session.user,
			"message_type": "Hire Request",
			"content": frappe.as_json(
				{
					"quote": row.name,
					"project": doc.name,
					"project_name": doc.project_name,
					"amount": row.amount,
					"weeks": row.timeline_weeks,
				}
			),
		}
	).insert(ignore_permissions=True)


def _post_system_message(thread: str | None, content: str):
	if thread:
		frappe.get_doc("Connect Thread", thread).post_system_message(content)


def _email_partner_admin(doc, row):
	admin = _get_partner_admin(row.partner)
	if admin:
		frappe.enqueue(
			"connect.customer.doctype.customer_project.hiring.send_hire_request_email",
			queue="short",
			enqueue_after_commit=True,
			admin=admin,
			project=doc.name,
			quote=row.name,
		)


def send_hire_request_email(admin: str, project: str, quote: str):
	"""Background job: a hire request is easy to miss in the in-app notification alone."""
	doc = frappe.get_doc("Customer Project", project)
	row = frappe.get_doc("Project Quote", quote)
	company = frappe.db.get_value("Customer", get_customer_for_user(doc.user), "customer_name") or doc.user
	amount = frappe.utils.fmt_money(row.amount or 0, currency="INR", precision=0)
	try:
		frappe.sendmail(
			recipients=[frappe.db.get_value("User", admin, "email") or admin],
			subject=_("{0} wants to hire you for {1}").format(company, doc.project_name),
			message=(
				f"<p>{escape_html(company)} {_('accepted your quote and wants you to take the project on.')}</p>"
				f"<p><b>{_('Project')}:</b> {escape_html(doc.project_name)}<br>"
				f"<b>{_('Your quote')}:</b> {amount}, {row.timeline_weeks or '?'} {_('weeks')}</p>"
				f"<p>{_('Accept or decline it within {0} days.').format(HIRE_REQUEST_EXPIRY_DAYS)}</p>"
				f"<p><a href='{get_url(f'/connect/messaging?thread={row.thread}')}'>{_('Open the conversation')}</a></p>"
			),
			now=True,
		)
	except Exception:
		frappe.log_error(title=f"Hire request email failed for {quote}")


def _partner_name(partner: str | None) -> str:
	return (frappe.db.get_value("Partner", partner, "partner_name") if partner else None) or partner or ""
