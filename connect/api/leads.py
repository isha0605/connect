import frappe

# Whitelisted entry points only. A lead is a Project Quote: the logic lives in
# connect/customer/doctype/project_quote/leads.py.


@frappe.whitelist()
def list_leads():
	from connect.customer.doctype.project_quote.leads import my_leads

	return my_leads()


@frappe.whitelist()
def get_lead(name):
	from connect.customer.doctype.project_quote.leads import get_lead

	return get_lead(name)


@frappe.whitelist(methods=["POST"])
def update_lead(name, stage=None, owner=None, probability=None, lost_reason=None):
	from connect.customer.doctype.project_quote.leads import update_lead

	return update_lead(name, stage, owner, probability, lost_reason)


@frappe.whitelist(methods=["POST"])
def add_lead_note(name, content):
	from connect.customer.doctype.project_quote.leads import add_lead_note

	return add_lead_note(name, content)


@frappe.whitelist(methods=["POST"])
def log_lead_follow_up(name, values):
	from connect.customer.doctype.project_quote.leads import log_lead_follow_up

	return log_lead_follow_up(name, values)
