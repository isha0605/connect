import frappe
from frappe import _
from frappe.utils import now_datetime

from connect.customer.doctype.customer_project.customer_project import get_own_project, project_dict
from connect.customer.doctype.customer_project.project_notifications import notify_customer, company_name

# The partner's customer stage that says the project is built, and the one it goes back to.
LIVE = "Live"
ONBOARDING = "Onboarding"


def mark_projects_live(partner_customer) -> None:
	"""Partner Customer.on_update: the partner moved this customer to Live, so each project they
	were hired for waits for the customer to confirm it's working."""
	for name in _hired_projects(partner_customer.partner, partner_customer.customer, live=False):
		doc = frappe.get_doc("Customer Project", name)
		doc.live_on = now_datetime()
		# A system step on the partner's stage change; only System Managers write projects.
		doc.save(ignore_permissions=True)
		notify_customer(
			doc,
			_("{0} marked {1} live").format(company_name(doc.partner), doc.project_name),
			_("Check your site, then confirm it's working."),
		)


def unmark_projects_live(partner_customer) -> None:
	"""Partner Customer.on_update: the partner took this customer off Live, so their projects
	are back to being built and can't be completed until they're marked live again."""
	for name in _hired_projects(partner_customer.partner, partner_customer.customer, live=True):
		doc = frappe.get_doc("Customer Project", name)
		doc.live_on = None
		# A system step on the partner's stage change; only System Managers write projects.
		doc.save(ignore_permissions=True)


def not_live_yet(name: str) -> dict:
	"""The customer's answer to a Live mark that came too soon: the project goes back to being
	built, the partner's customer back to Onboarding, and the partner reads why in their chat."""
	doc = get_own_project(name)
	if doc.status != "Hired" or not doc.live_on:
		frappe.throw(_("{0} hasn't marked this project live.").format(company_name(doc.partner)))

	doc.live_on = None
	# get_own_project checked the caller owns this project.
	doc.save(ignore_permissions=True)
	thread, customer = _hired_thread_and_customer(doc)
	_move_partner_customer_back(doc.partner, customer)
	if thread:
		frappe.get_doc("Connect Thread", thread).post_system_message(
			_("{0} says {1} isn't live yet.").format(customer, doc.project_name)
		)
	return project_dict(doc)


def _hired_projects(partner: str, customer: str, live: bool) -> list[str]:
	"""The customer's projects in progress with this partner, already marked live or not.
	The Live stage is per customer, so it covers each of them."""
	Project = frappe.qb.DocType("Customer Project")
	Quote = frappe.qb.DocType("Project Quote")
	Thread = frappe.qb.DocType("Connect Thread")
	return (
		frappe.qb.from_(Project)
		.join(Quote)
		.on(Quote.name == Project.hired_quote)
		.join(Thread)
		.on(Thread.name == Quote.thread)
		.select(Project.name)
		.where(Project.partner == partner)
		.where(Thread.customer == customer)
		.where(Project.status == "Hired")
		.where(Project.live_on.isnotnull() if live else Project.live_on.isnull())
		.run(pluck=True)
	)


def _hired_thread_and_customer(doc) -> tuple[str | None, str | None]:
	thread = frappe.db.get_value("Project Quote", doc.hired_quote, "thread")
	return thread, thread and frappe.db.get_value("Connect Thread", thread, "customer")


def _move_partner_customer_back(partner: str, customer: str | None) -> None:
	name = frappe.db.get_value("Partner Customer", {"partner": partner, "customer": customer, "stage": LIVE}, "name")
	if not name:
		return
	record = frappe.get_doc("Partner Customer", name)
	record.stage = ONBOARDING
	# The customer's answer moves the partner's record; neither side writes it directly.
	# Activity is read from the Version history, so the change is recorded there.
	record.save(ignore_permissions=True, ignore_version=False)
