import frappe

# Whitelisted entry points only — the logic lives next to the Customer Project and
# Starter Pack Order doctypes. See connect/api/customer.py for why.


@frappe.whitelist()
def list_projects():
	"""Everything on the Projects page, newest first: draft projects and paid Starter
	Pack orders. Each row says which kind it is, since they open different pages."""
	from connect.customer.doctype.customer_project.customer_project import my_projects
	from connect.customer.doctype.starter_pack_order.starter_pack_order import my_orders

	orders = [{"kind": "order", **row} for row in my_orders()]
	return sorted(my_projects() + orders, key=lambda row: row["created_on"] or "", reverse=True)


@frappe.whitelist(methods=["POST"])
def save_project(
	project_name, go_live=None, operations=None, problems=None, verdict=None, name=None, systems=None,
	industries=None, company_size=None,
):
	from connect.customer.doctype.customer_project.customer_project import save_project
	return save_project(project_name, go_live, operations, problems, verdict, name, systems, industries, company_size)


@frappe.whitelist()
def get_project(name):
	from connect.customer.doctype.customer_project.customer_project import get_project
	return get_project(name)


@frappe.whitelist(methods=["POST"])
def share_requirements(name, budget=None, description=None):
	from connect.customer.doctype.customer_project.customer_project import share_requirements
	return share_requirements(name, budget, description)


@frappe.whitelist(methods=["POST"])
def delete_project(name):
	from connect.customer.doctype.customer_project.customer_project import delete_project
	return delete_project(name)


# Guests too: the Find Partners questions show the live count before anyone signs up. It
# only counts partners the public directory already lists.
@frappe.whitelist(allow_guest=True)
def partner_criteria(criteria=None):
	from connect.customer.doctype.customer_project.customer_project import partner_criteria
	return partner_criteria(criteria)


@frappe.whitelist(methods=["POST"])
def save_criteria(name, criteria=None, go_live=None):
	from connect.customer.doctype.customer_project.customer_project import save_criteria
	return save_criteria(name, criteria, go_live)


@frappe.whitelist()
def list_quotes(name):
	from connect.customer.doctype.customer_project.customer_project import list_quotes
	return list_quotes(name)


@frappe.whitelist(methods=["POST"])
def set_quote_status(quote, status):
	from connect.customer.doctype.customer_project.customer_project import set_quote_status
	return set_quote_status(quote, status)


# Demo only: partners can't send quotes yet. See simulate_quotes.
@frappe.whitelist(methods=["POST"])
def simulate_quotes(name):
	from connect.customer.doctype.customer_project.customer_project import simulate_quotes
	return simulate_quotes(name)


@frappe.whitelist(methods=["POST"])
def hire_partner(quote):
	from connect.customer.doctype.customer_project.customer_project import hire_partner
	return hire_partner(quote)


@frappe.whitelist(methods=["POST"])
def set_hire_reason(name, reason=None):
	from connect.customer.doctype.customer_project.customer_project import set_hire_reason
	return set_hire_reason(name, reason)


@frappe.whitelist(methods=["POST"])
def complete_task(name, task):
	from connect.customer.doctype.customer_project.customer_project import complete_task
	return complete_task(name, task)


@frappe.whitelist(methods=["POST"])
def complete_project(name):
	from connect.customer.doctype.customer_project.customer_project import complete_project
	return complete_project(name)
