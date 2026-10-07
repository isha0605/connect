"""Sign in and sign up with an emailed code: the two calls the login and sign-up screens make.
See connect.auth.accounts for what happens behind them."""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import validate_email_address

from connect.auth.accounts import BUYER, PARTNER, send_sign_in_code, sign_in_with_code
from connect.auth.email_code import EmailCode

NAME_MAX_LENGTH = 140


# Open to guests: sending is limited by IP and by email, and the reply is the same for any email.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=EmailCode.TTL_SECONDS, methods="POST")
@rate_limit(key="email", ip_based=False, limit=5, seconds=EmailCode.TTL_SECONDS, methods="POST")
def send_code(email, full_name=None, company_name=None, country=None, flow=BUYER):
	"""Email a sign-in code. A new email gets one too: the account is made when it's checked.
	The sign-up form sends its details here, so the code screen only has to send the code."""
	email = validated_email(email)
	send_sign_in_code(email, profile_details(full_name, company_name, country, flow))
	return {"message": _("We sent a code to {0}.").format(email)}


# Open to guests: a short-lived code and its try limit sign the person in.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=EmailCode.TTL_SECONDS, methods="POST")
@rate_limit(key="email", ip_based=False, limit=10, seconds=EmailCode.TTL_SECONDS, methods="POST")
def verify_code(email, code, full_name=None, company_name=None, country=None, flow=None, next=None):
	"""Sign in with an emailed code. Answers `needs_profile` (with what's `missing`) while a new
	account still needs its name or company, else `redirect`: where to go next."""
	email = validated_email(email)
	if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
		frappe.throw(_("Enter the 6-digit code from your email."), frappe.ValidationError)
	details = profile_details(full_name, company_name, country, flow)
	details["next"] = next
	return sign_in_with_code(email, code, details)


def validated_email(email):
	if not isinstance(email, str) or len(email) > 254:
		frappe.throw(_("Enter a valid email address."), frappe.ValidationError)
	email = email.strip().lower()
	if validate_email_address(email, throw=False) != email:
		frappe.throw(_("Enter a valid email address."), frappe.ValidationError)
	return email


def profile_details(full_name, company_name, country, flow):
	"""The sign-up details, checked; only what was given, so a later call doesn't blank them."""
	if flow not in (None, BUYER, PARTNER):
		frappe.throw(_("Unknown sign-up."), frappe.ValidationError)
	details = {"flow": flow}
	for key, value, label in (
		("full_name", full_name, _("your full name")),
		("company_name", company_name, _("your company name")),
		("country", country, _("your country")),
	):
		if value is None:
			continue
		value = str(value).strip()
		if not value:
			frappe.throw(_("Enter {0}.").format(label), frappe.ValidationError)
		if len(value) > NAME_MAX_LENGTH:
			frappe.throw(_("Use a shorter name for {0}.").format(label), frappe.ValidationError)
		details[key] = value
	return {k: v for k, v in details.items() if v}
