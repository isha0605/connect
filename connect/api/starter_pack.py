import frappe
from frappe.rate_limiter import rate_limit

# Whitelisted entry points only — the logic lives next to the Starter Pack and
# Starter Pack Order doctypes. See connect/api/customer.py for why.
#
# Checkout is open to guests: sign-in is a mock today, and the buyer is whoever the form
# names. Placing an order opens a Razorpay payment link, so it's rate limited per IP.


@frappe.whitelist(allow_guest=True)
def get_catalog():
	from connect.customer.doctype.starter_pack.starter_pack import get_catalog
	return get_catalog()


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=60 * 60)
def checkout(packs, company_name, phone=None, terms_accepted=0, buyer_name=None, buyer_email=None):
	from connect.customer.doctype.starter_pack_order.starter_pack_order import checkout
	return checkout(
		packs,
		company_name,
		phone=phone,
		terms_accepted=terms_accepted,
		buyer_name=buyer_name,
		buyer_email=buyer_email,
	)


# POST only: an unpaid order is re-synced from the gateway here, which can mark it Paid
# and assign its partner — and Frappe rolls back whatever a GET request writes.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_order(order=None, payment_request=None, key=None):
	from connect.customer.doctype.starter_pack_order.starter_pack_order import get_order
	return get_order(order=order, payment_request=payment_request, key=key)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=60 * 60)
def pay(order, key=None):
	from connect.customer.doctype.starter_pack_order.starter_pack_order import pay
	return pay(order, key=key)
