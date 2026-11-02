import frappe

# Whitelisted entry points only: the logic lives in connect/partner/doctype/partner_customer/customers.py.


@frappe.whitelist()
def list_customers():
	from connect.partner.doctype.partner_customer.customers import my_customers

	return my_customers()


@frappe.whitelist()
def get_customer(name):
	from connect.partner.doctype.partner_customer.customers import get_customer

	return get_customer(name)


@frappe.whitelist(methods=["POST"])
def update_customer(name, stage=None, assigned_to=None):
	from connect.partner.doctype.partner_customer.customers import update_customer

	return update_customer(name, stage, assigned_to)


@frappe.whitelist(methods=["POST"])
def add_customer_note(name, content):
	from connect.partner.doctype.partner_customer.customers import add_customer_note

	return add_customer_note(name, content)


@frappe.whitelist(methods=["POST"])
def log_customer_follow_up(name, values):
	from connect.partner.doctype.partner_customer.customers import log_customer_follow_up

	return log_customer_follow_up(name, values)
