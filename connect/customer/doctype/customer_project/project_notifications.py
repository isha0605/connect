import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

# What the customer is told when their project reaches each status. Shared is announced only
# the first time, since a declined or withdrawn hire also puts the project back to Shared.
STATUS_SUBJECTS = {
	"Shared": lambda doc: shared_subject(doc.shared_count or 0),
	"Hiring": lambda doc: _("Hire request sent to {0}").format(company_name(doc.partner)),
	"Hired": lambda doc: _("{0} accepted your project").format(company_name(doc.partner)),
	"Completed": lambda doc: _("Project completed"),
}


def shared_subject(count: int) -> str:
	if count == 1:
		return _("Requirements sent to 1 partner")
	return _("Requirements sent to {0} partners").format(count)


def notify_project_created(doc) -> None:
	notify_customer(doc, _("Project created"), doc.project_name)


def notify_project_step(doc) -> None:
	"""Tells the customer their project moved on, once per status change."""
	before = doc.get_doc_before_save()
	if not before or before.status == doc.status or doc.status not in STATUS_SUBJECTS:
		return
	if doc.status == "Shared" and before.status != "Draft":
		return

	notify_customer(doc, STATUS_SUBJECTS[doc.status](doc), doc.project_name)


def notify_quote_update(quote) -> None:
	"""Tells the customer when a partner quotes, declines the brief, or declines their hire request."""
	before = quote.get_doc_before_save()
	if not before or before.status == quote.status:
		return

	project = frappe.get_doc("Customer Project", quote.customer_project)
	if quote.status == "Quoted" and before.status == "Awaiting":
		notify_customer(project, _("New quote from {0}").format(company_name(quote.partner)), quote_summary(project, quote))
	elif quote.status == "Partner Declined":
		notify_customer(
			project,
			_("{0} is not available to take on new clients").format(company_name(quote.partner)),
			project.project_name,
		)
	elif quote.status == "Hire Declined":
		notify_customer(
			project,
			_("{0} declined your hire request").format(company_name(quote.partner)),
			quote.decline_reason or project.project_name,
		)
		frappe.enqueue(
			"connect.customer.doctype.customer_project.project_notifications.send_hire_declined_email",
			queue="short",
			enqueue_after_commit=True,
			quote=quote.name,
		)


def notify_customer(project, subject: str, body: str) -> None:
	# No from_user: Frappe skips notifying the person who acted, and "Project created" is the
	# customer's own action.
	enqueue_create_notification(
		[project.user],
		{
			"type": "Alert",
			"document_type": "Customer Project",
			"document_name": project.name,
			"subject": subject[:140],
			"email_content": body,
			"link": project_link(project),
		},
	)


def project_link(project) -> str:
	"""The project's page in the Connect app, the same one the Projects list opens."""
	page = "/custom-implementation" if project.verdict == "Custom" else "/starter-pack-recommendation"
	return f"{page}?project={project.name}"


def quote_amount(amount, currency: str) -> str:
	"""A quote's amount as messages and emails show it, in the quote's currency: ₹4,00,000 or $4,800."""
	return frappe.utils.fmt_money(amount or 0, currency=currency, precision=0).replace(" ", "", 1)


def quote_summary(project, quote) -> str:
	parts = [project.project_name, quote_amount(quote.amount, quote.currency)]
	if quote.timeline_weeks:
		parts.append(_("{0} weeks").format(quote.timeline_weeks))
	return " · ".join(parts)


def company_name(partner: str | None) -> str:
	return (partner and frappe.db.get_value("Partner", partner, "company_name")) or partner or _("A partner")


def email_quote_declined(quote) -> None:
	"""Project Quote.on_update: the customer set this quote aside, so the partner's owners and the
	lead's owner are emailed which quote and why, after the change commits."""
	from connect.permissions import _get_partner_admins

	recipients = set(_get_partner_admins(quote.partner))
	if quote.lead:
		recipients.add(frappe.db.get_value("Partner Lead", quote.lead, "assigned_to"))
	for user in filter(None, recipients):
		frappe.enqueue(
			"connect.customer.doctype.customer_project.project_notifications.send_quote_declined_email",
			queue="short",
			enqueue_after_commit=True,
			user=user,
			quote=quote.name,
		)


def send_quote_declined_email(user: str, quote: str) -> None:
	"""Background job: tells one partner team member the customer declined their quote, and why."""
	row = frappe.get_doc("Project Quote", quote)
	if row.status != "Not Interested":
		return  # restored before the email went out
	customer = frappe.db.get_value("Connect Thread", row.thread, "customer")
	company = frappe.db.get_value("Customer", customer, "customer_name") or customer or _("A customer")
	project = frappe.db.get_value("Customer Project", row.customer_project, "project_name")
	send_decision_email(
		user,
		subject=_("{0} declined your quote for {1}").format(company, project),
		intro=_("{0} is not taking your quote forward.").format(company),
		rows=[
			(_("Project"), project),
			(_("Your quote"), offer_line(row)),
			(_("Reason"), _(row.not_interested_reason or "")),
			(_("Their note"), row.not_interested_note),
		],
		link=(_("Open the lead"), f"/connect/leads/{row.lead}" if row.lead else "/connect/leads"),
		quote=quote,
	)


def send_hire_declined_email(quote: str) -> None:
	"""Background job: tells the customer the partner declined their hire request, and why."""
	row = frappe.get_doc("Project Quote", quote)
	if row.status != "Hire Declined":
		return
	project = frappe.get_doc("Customer Project", row.customer_project)
	partner = company_name(row.partner)
	send_decision_email(
		project.user,
		subject=_("{0} declined your hire request for {1}").format(partner, project.project_name),
		intro=_("{0} can't take on this project.").format(partner),
		rows=[
			(_("Project"), project.project_name),
			(_("Their quote"), offer_line(row)),
			(_("Reason"), row.decline_reason),
		],
		# A hire only happens on a custom implementation, so its page is where to choose again.
		link=(_("Choose another partner"), f"/connect/custom-implementation?project={project.name}"),
		quote=quote,
	)


def offer_line(row) -> str:
	"""A quote as one line: ₹8,75,000 · 8 weeks."""
	offer = quote_amount(row.amount, row.currency)
	return offer + " · " + _("{0} weeks").format(row.timeline_weeks) if row.timeline_weeks else offer


def send_decision_email(user: str, subject: str, intro: str, rows: list, link: tuple, quote: str) -> None:
	"""The email both sides get when the other turns a quote or hire down: what happened, the
	quote and the reason as labelled lines (empty ones left out), and where to go next."""
	from frappe.utils import escape_html, get_url

	lines = "<br>".join(f"<b>{escape_html(label)}:</b> {escape_html(value)}" for label, value in rows if value)
	label, path = link
	try:
		frappe.sendmail(
			recipients=[frappe.db.get_value("User", user, "email") or user],
			subject=subject,
			message=(
				f"<p>{escape_html(intro)}</p>"
				f"<p>{lines}</p>"
				f"<p><a href='{get_url(path)}'>{escape_html(label)}</a></p>"
			),
			now=True,
		)
	except Exception:
		frappe.log_error(title=f"Decision email failed for {quote}")
