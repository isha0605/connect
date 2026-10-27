import frappe
from frappe.rate_limiter import rate_limit

# Whitelisted entry points only — the logic lives next to the Starter Pack and
# Starter Pack Order doctypes. See connect/api/customer.py for why.
#
# Checkout needs a signed-in buyer (it refuses guests with a message, rather than a bare 403).
# Placing an order opens a Razorpay payment link, so it's rate limited per IP. Reading an order
# back and paying again stay open to guests, with the order's access key.


@frappe.whitelist(allow_guest=True)
def get_catalog():
	from connect.starter_packs.doctype.starter_pack.starter_pack import get_catalog
	return get_catalog()


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=60 * 60)
def checkout(packs, company_name, phone=None, terms_accepted=0, buyer_name=None, buyer_email=None, project=None):
	from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import checkout
	return checkout(
		packs,
		company_name,
		phone=phone,
		terms_accepted=terms_accepted,
		buyer_name=buyer_name,
		buyer_email=buyer_email,
		project=project,
	)


# POST only: an unpaid order is re-synced from the gateway here, which can mark it Paid
# and assign its partner — and Frappe rolls back whatever a GET request writes.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_order(order=None, payment_request=None, key=None):
	from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import get_order
	return get_order(order=order, payment_request=payment_request, key=key)


# POST + rate limited: it answers questions about an email address, and sign-in is a mock,
# so this must not be cheap to crawl.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=60 * 60)
def last_checkout_details(email=None):
	from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import last_checkout_details
	return last_checkout_details(email)


@frappe.whitelist(methods=["POST"])
def save_company_details(order, employees, industry, system, focus=None, key=None):
	from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import save_company_details
	return save_company_details(order, employees, industry, system, focus=focus, key=key)


@frappe.whitelist(methods=["POST"])
def share_kickoff_meeting(thread, link, starts_at):
	from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import share_kickoff_meeting
	return share_kickoff_meeting(thread, link, starts_at)


@frappe.whitelist()
def my_orders():
	from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import my_orders
	return my_orders()


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=60 * 60)
def pay(order, key=None):
	from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import pay
	return pay(order, key=key)


@frappe.whitelist()
def get_my_projects():
	from connect.starter_packs.doctype.starter_pack_order.starter_pack_order import get_my_projects
	return get_my_projects()
