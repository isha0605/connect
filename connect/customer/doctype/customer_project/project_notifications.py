import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

# What the customer is told when their project reaches each status. Shared is announced only
# the first time, since a declined or withdrawn hire also puts the project back to Shared.
STATUS_SUBJECTS = {
	"Shared": lambda doc: _("Requirements sent to {0} partners").format(doc.shared_count or 0),
	"Hiring": lambda doc: _("Hire request sent to {0}").format(partner_name(doc.partner)),
	"Hired": lambda doc: _("{0} accepted your project").format(partner_name(doc.partner)),
	"Completed": lambda doc: _("Project completed"),
}


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
	"""Tells the customer when a partner quotes or declines their hire request."""
	before = quote.get_doc_before_save()
	if not before or before.status == quote.status:
		return

	project = frappe.get_doc("Customer Project", quote.customer_project)
	if quote.status == "Quoted" and before.status == "Awaiting":
		notify_customer(project, _("New quote from {0}").format(partner_name(quote.partner)), quote_summary(project, quote))
	elif quote.status == "Hire Declined":
		notify_customer(
			project,
			_("{0} declined your hire request").format(partner_name(quote.partner)),
			quote.decline_reason or project.project_name,
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


def quote_summary(project, quote) -> str:
	amount = frappe.utils.fmt_money(quote.amount or 0, currency="INR", precision=0).replace("₹ ", "₹")
	parts = [project.project_name, amount]
	if quote.timeline_weeks:
		parts.append(_("{0} weeks").format(quote.timeline_weeks))
	return " · ".join(parts)


def partner_name(partner: str | None) -> str:
	return (partner and frappe.db.get_value("Partner", partner, "partner_name")) or partner or _("A partner")
