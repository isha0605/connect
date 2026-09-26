import frappe

# Whitelisted entry points only — the logic lives next to the Starter Pack and
# Starter Pack Order doctypes. See connect/api/customer.py for why.


@frappe.whitelist(allow_guest=True)
def get_catalog():
	from connect.customer.doctype.starter_pack.starter_pack import get_catalog
	return get_catalog()


@frappe.whitelist()
def checkout(packs, company_name, phone=None, terms_accepted=0):
	from connect.customer.doctype.starter_pack_order.starter_pack_order import checkout
	return checkout(packs, company_name, phone=phone, terms_accepted=terms_accepted)


@frappe.whitelist()
def get_order(order):
	from connect.customer.doctype.starter_pack_order.starter_pack_order import get_order
	return get_order(order)


@frappe.whitelist()
def pay(order):
	from connect.customer.doctype.starter_pack_order.starter_pack_order import pay
	return pay(order)
