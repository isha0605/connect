# Copyright (c) 2026
# For license information, please see license.txt

"""Signing in and signing up with an emailed code.

Every email gets a code. A known email signs in; a new one becomes an account once its code
is checked. Two kinds of new account:

- a buyer (the sign-up form): a Website User, their Customer company and an admin team
  membership, so chat, the shortlist, requirements and orders all work straight away;
- a partner (from "Become a partner"): only the Website User. Partner Onboarding makes the
  Partner, as it does for a password sign-up.

Frappe consultants and anyone added to a team or a chat already have a User, so they only
ever sign in.
"""

import frappe
from frappe import _
from frappe.utils import cint, escape_html, random_string

from connect.auth.email_code import EmailCode
from connect.roles import CONSULTANT_ROLE

BUYER, PARTNER = "buyer", "partner"


# ---- Sending a code ----


def send_sign_in_code(email, details=None):
	"""Email a code to any address. A disabled account gets a notice instead, so nobody can
	tell from the reply whether an account exists or is disabled."""
	user = find_user(email)
	if user and not user.enabled:
		send_disabled_notice(email)
	elif user:
		EmailCode(email).send(_("{0} is your Frappe Connect sign-in code"), _("Sign in to Frappe Connect"))
	else:
		if (details or {}).get("company_name"):
			check_company_is_free(details["company_name"])
		EmailCode(email).send(
			_("{0} is your Frappe Connect sign-up code"), _("Create your Frappe Connect account"), details
		)


# ---- Checking it ----


def sign_in_with_code(email, code, details=None):
	"""Sign in with a checked code, creating the account for a new address. A new address
	needs its profile (a name, and for a buyer a company); without it the code stays valid,
	so the person can add it and send the same code again."""
	email_code = EmailCode(email)
	with email_code.lock():
		pending = email_code.verify(code)
		user = find_user(email)
		if user and not user.enabled:
			frappe.throw(_("This account is disabled. Contact Frappe to restore access."), frappe.ValidationError)

		if not user:
			given = {k: v for k, v in (details or {}).items() if v}
			profile = {**(pending.get("details") or {}), **given}
			missing = missing_profile(profile)
			if missing:
				email_code.remember(given)
				return {"needs_profile": True, "missing": missing}
			name = create_account(email, profile)
		else:
			name = user.name
		email_code.discard()

	frappe.local.login_manager.login_as(name)
	return {"user": name, "redirect": landing_page(name, (details or {}).get("next"))}


def missing_profile(profile):
	"""What a new account still needs: a name, and for a buyer their company."""
	missing = [] if profile.get("full_name") else ["full_name"]
	if profile.get("flow", BUYER) == BUYER and not profile.get("company_name"):
		missing.append("company_name")
	return missing


# ---- Making the account ----


def create_account(email, profile):
	"""A Website User, and for a buyer their Customer and an admin membership of it."""
	user = create_user(email, profile["full_name"], profile.get("country"))
	if profile.get("flow", BUYER) == BUYER:
		create_customer(user.name, profile["full_name"], profile["company_name"], profile.get("country"))
	# Last, since joining a customer team saves the User again (it adds the customer role).
	made_by(user, user.name)
	return user.name


def create_user(email, full_name, country=None):
	"""A Website User whose email is already checked: no password to remember (a random one,
	never sent) and no welcome email."""
	enforce_signup_limit()
	first_name, _sep, last_name = escape_html(full_name).strip().partition(" ")
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": first_name,
			"last_name": last_name,
			"enabled": 1,
			"new_password": random_string(16),
			"user_type": "Website User",
			"location": country or None,
		}
	)
	user.flags.ignore_password_policy = True
	user.flags.no_welcome_mail = True
	# A guest makes the account, and a guest has no permission to create a User.
	user.insert(ignore_permissions=True)
	return user


def create_customer(user, full_name, company_name, country=None):
	check_company_is_free(company_name)
	customer = frappe.get_doc(
		{"doctype": "Customer", "customer_name": company_name.strip(), "country": country or None}
	).insert(ignore_permissions=True)
	made_by(customer, user)
	member = frappe.get_doc(
		{
			"doctype": "Customer Team Member",
			"customer": customer.name,
			"user": user,
			"full_name": full_name,
			"is_admin": 1,
		}
	).insert(ignore_permissions=True)
	made_by(member, user)
	return customer.name


def made_by(doc, user):
	"""Records the person signing up, not Guest, as who made a record: they aren't signed in
	until their code is checked, and an insert always takes the session's user as its owner."""
	doc.db_set({"owner": user, "modified_by": user}, update_modified=False)


def check_company_is_free(company_name):
	"""One Customer per company: someone joining a company already here is added by its admin."""
	company_name = (company_name or "").strip()
	if frappe.db.exists("Customer", {"customer_name": company_name}):
		frappe.throw(
			_("{0} is already registered. Ask your team admin to add you instead.").format(frappe.bold(company_name)),
			frappe.ValidationError,
		)


def enforce_signup_limit():
	"""A cap on new accounts an hour, across the site, against bots (System Settings)."""
	limit = cint(frappe.get_system_settings("max_signups_allowed_per_hour") or 300)
	if frappe.db.get_creation_count("User", 60) >= limit:
		frappe.throw(
			_("Too many people signed up recently. Please try again in an hour."), frappe.TooManyRequestsError
		)


# ---- Where they land ----


def landing_page(user, next_path=None):
	"""The page asked for, if it's one of ours; else by who they are: a Frappe consultant or a
	partner to Messaging (a partner still applying to Partner Onboarding), anyone else Home."""
	if is_own_path(next_path):
		return next_path
	if CONSULTANT_ROLE in frappe.get_roles(user):
		return "/connect/messaging"
	if frappe.db.exists("Partner Application", {"owner": user, "status": "Draft"}):
		return "/connect/partner-onboarding"
	if frappe.db.exists("Connect Partner Member", {"user": user, "is_removed": 0}):
		return "/connect/messaging"
	return "/connect/home" if home_is_published() else "/connect/partner-directory-redesign"


def home_is_published():
	"""Home is still a draft for now; until it's published, buyers start on the partner directory."""
	return bool(frappe.db.get_value("Studio Page", {"route": "/home"}, "published"))


def is_own_path(path):
	"""A path on this site, never another one: "/connect/x", not "//evil.com" or "https://…"."""
	return bool(path) and isinstance(path, str) and path.startswith("/") and not path.startswith("//") and "\\" not in path


# ---- Helpers ----


def find_user(email):
	return frappe.db.get_value("User", {"email": email}, ["name", "enabled"], as_dict=True)


def send_disabled_notice(email):
	"""Never fails the request: a failure here would make a disabled account's reply differ."""
	try:
		frappe.sendmail(
			recipients=[email],
			subject=_("Your Frappe Connect account is disabled"),
			message=_(
				"Someone tried to sign in to Frappe Connect with this email, but the account is disabled. "
				"If this was you, contact Frappe to restore access."
			),
			now=True,
		)
	except Exception:
		frappe.log_error(title="Disabled-account notice could not be sent")
		frappe.clear_messages()
