"""Review requests: a partner asks a past customer for a review, and the customer answers from the
emailed link. The behaviour lives on Review Request."""

import frappe
from frappe.rate_limiter import rate_limit

from connect.partner.doctype.review_request import review_request

# A link's token is long and random; this only slows down anyone trying links at random.
LINK_TRIES_AN_HOUR = 20


@frappe.whitelist()
def list_review_requests():
	return review_request.my_requests()


@frappe.whitelist(methods=["POST"])
def create_review_request(values, send=False):
	return review_request.create_request(values, send)


@frappe.whitelist(methods=["POST"])
def send_review_request(name):
	return review_request.send_request(name)


@frappe.whitelist(methods=["POST"])
def remind_review_request(name):
	return review_request.remind_request(name)


@frappe.whitelist(methods=["POST"])
def withdraw_review_request(name):
	return review_request.withdraw_request(name)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=LINK_TRIES_AN_HOUR, seconds=60 * 60, methods="POST")
def open_review_request(token):
	return review_request.open_request(token)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=LINK_TRIES_AN_HOUR, seconds=60 * 60, methods="POST")
def accept_review_request(token, full_name=None, company_name=None):
	return review_request.accept_request(token, full_name, company_name)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=LINK_TRIES_AN_HOUR, seconds=60 * 60, methods="POST")
def decline_review_request(token, reason=None):
	return review_request.decline_request(token, reason)
