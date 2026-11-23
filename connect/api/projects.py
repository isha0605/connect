import frappe

# Whitelisted entry points only — the logic lives next to the Customer Project and
# Starter Pack Order doctypes. See connect/api/customer.py for why.


@frappe.whitelist()
def list_projects():
	"""Everything on the Projects page, newest first: draft projects and paid Starter
	Pack orders. Each row says which kind it is, since they open different pages."""
	from connect.customer.doctype.customer_project.customer_project import my_projects
	from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import my_orders

	orders = [{"kind": "order", **row} for row in my_orders()]
	return sorted(my_projects() + orders, key=lambda row: row["created_on"] or "", reverse=True)


# `answers` is the project questions' answers as one JSON object; see questions.py.
@frappe.whitelist(methods=["POST"])
def start_project_with_partner(partner, project=None, answers=None):
	from connect.customer.doctype.customer_project.customer_project import start_project_with_partner
	return start_project_with_partner(partner, project, answers)


@frappe.whitelist()
def get_project(name):
	from connect.customer.doctype.customer_project.customer_project import get_project
	return get_project(name)


@frappe.whitelist(methods=["POST"])
def update_requirements(name, answers):
	from connect.customer.doctype.customer_project.customer_project import update_requirements
	return update_requirements(name, answers)


# The customer's side: Edit on their own Requirement card in a chat.
@frappe.whitelist()
def editable_briefs(thread):
	from connect.customer.doctype.customer_project.brief import editable_briefs
	return editable_briefs(thread)


@frappe.whitelist(methods=["POST"])
def share_requirements(answers, contact_partners=False):
	from connect.customer.doctype.customer_project.customer_project import share_requirements
	return share_requirements(answers, frappe.utils.sbool(contact_partners))


# Guests too: the Find Partners questions show the live count before anyone signs up. It
# only counts partners the public directory already lists.
@frappe.whitelist(allow_guest=True)
def partner_criteria(criteria=None, include_recipients=False):
	from connect.customer.doctype.customer_project.partner_matching import partner_criteria
	return partner_criteria(criteria, frappe.utils.sbool(include_recipients))


@frappe.whitelist()
def list_quotes(name):
	from connect.customer.doctype.customer_project.customer_project import list_quotes
	return list_quotes(name)


@frappe.whitelist(methods=["POST"])
def set_quote_status(quote, status):
	from connect.customer.doctype.customer_project.customer_project import set_quote_status
	return set_quote_status(quote, status)


# Demo only: every partner still Awaiting replies with a made-up quote. See simulate_quotes.
@frappe.whitelist(methods=["POST"])
def simulate_quotes(name):
	from connect.customer.doctype.customer_project.demo_quotes import simulate_quotes
	return simulate_quotes(name)


@frappe.whitelist(methods=["POST"])
def hire_partner(quote):
	from connect.customer.doctype.customer_project.hiring import hire_partner
	return hire_partner(quote)


@frappe.whitelist(methods=["POST"])
def cancel_hire_request(name):
	from connect.customer.doctype.customer_project.hiring import cancel_hire_request
	return cancel_hire_request(name)


@frappe.whitelist()
def hire_request_statuses(thread):
	from connect.customer.doctype.customer_project.hiring import hire_request_statuses
	return hire_request_statuses(thread)


@frappe.whitelist()
def quote_card_statuses(thread):
	from connect.customer.doctype.customer_project.hiring import quote_card_statuses
	return quote_card_statuses(thread)


# The partner's side: their owners and sales quote on a brief from the chat.
@frappe.whitelist(methods=["POST"])
def decline_brief(quote):
	frappe.get_doc("Project Quote", quote).decline_brief()


@frappe.whitelist()
def quotable_briefs(thread):
	from connect.customer.doctype.project_quote.project_quote import quotable_briefs
	return quotable_briefs(thread)


@frappe.whitelist(methods=["POST"])
def send_quote(quote, amount, weeks, note=None, brochure=None):
	return {"message": frappe.get_doc("Project Quote", quote).send_quote(amount, weeks, note, brochure)}


@frappe.whitelist(methods=["POST"])
def confirm_quote(quote):
	frappe.get_doc("Project Quote", quote).confirm_quote()


# The partner's side: their admin answers the request from the card in the thread.
@frappe.whitelist(methods=["POST"])
def respond_to_hire(quote, accept, reason=None):
	from connect.customer.doctype.customer_project.hiring import respond_to_hire
	return respond_to_hire(quote, accept, reason)


@frappe.whitelist(methods=["POST"])
def set_hire_reason(name, reasons=None, note=None):
	from connect.customer.doctype.customer_project.customer_project import set_hire_reason
	return set_hire_reason(name, reasons, note)


@frappe.whitelist(methods=["POST"])
def complete_task(name, task):
	from connect.customer.doctype.customer_project.customer_project import complete_task
	return complete_task(name, task)


@frappe.whitelist(methods=["POST"])
def not_live_yet(name):
	from connect.customer.doctype.customer_project.going_live import not_live_yet
	return not_live_yet(name)


@frappe.whitelist(methods=["POST"])
def complete_project(name):
	from connect.customer.doctype.customer_project.customer_project import complete_project
	return complete_project(name)
