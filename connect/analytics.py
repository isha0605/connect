import hashlib
import re

import frappe
from frappe.utils.telemetry.pulse import client as pulse
from frappe.utils.telemetry.pulse.transport import PulseHTTP

from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.roles import CONSULTANT_ROLE, PARTNER_GUEST_ROLE, PARTNER_ROLE

APP = "connect"
# Only the customer journey is measured: partners and Frappe staff would skew its numbers.
UNTRACKED_ROLES = {PARTNER_ROLE, PARTNER_GUEST_ROLE, CONSULTANT_ROLE, "System Manager"}
# What Pulse's cookieless client calls a visitor: "anon_" and a sha256.
VISITOR_ID = re.compile(r"^anon_[0-9a-f]{16,64}$")


def get_browser_config() -> dict:
	"""What the browser needs to send this visitor's events to Pulse, or `enabled: False`
	when this visitor isn't tracked or telemetry is off."""
	user = frappe.session.user
	if is_untracked_user(user):
		return {"enabled": False}

	config = pulse.boot_config()
	if config.get("enabled"):
		config["team"] = get_team(user)
		# Browsers import the client as a module, which needs CORS on Pulse's asset. A bench
		# that has the Pulse app can serve the same file from this site instead.
		config["client_url"] = frappe.conf.get("pulse_client_url") or config["client_url"]
	return config


def capture(event: str, user: str, properties: dict | None = None) -> None:
	"""Record a step of `user`'s journey that the server is sure of, like a payment. A guest
	has no account to tie it to, so it isn't sent."""
	# test runs share the site, and their made-up journeys must not reach the real numbers
	if frappe.flags.in_test or not user or user == "Guest" or is_untracked_user(user):
		return
	pulse.capture(event, APP, user=user, team=get_team(user), properties=properties)


def record_signup(user: str, country: str | None, visitor_id: str | None) -> None:
	"""A new buyer's account, and the browsing they did before it."""
	capture("signup_completed", user, {"country": country})

	team = get_team(user)
	if (
		team
		and visitor_id
		and not frappe.flags.in_test
		and VISITOR_ID.match(visitor_id)
		and pulse.is_enabled()
	):
		frappe.enqueue(link_visitor, visitor_id=visitor_id, team=team, enqueue_after_commit=True)


def link_visitor(visitor_id: str, team: str) -> None:
	"""Tell Pulse a visitor's id belongs to this customer. Frappe's own `alias()` always
	links to the site's single team; Connect has one team per customer."""
	PulseHTTP().post("/api/method/pulse.api.alias", {"previous_id": visitor_id, "team": team}, label="alias")


def get_team(user: str) -> str | None:
	"""The customer `user` buys for, as Pulse's account id."""
	customer = get_customer_for_user(user)
	return team_id(customer) if customer else None


def team_id(customer: str) -> str:
	# Hashed like Frappe's `user_` ids, so Pulse never holds a company's name.
	digest = hashlib.sha256(f"{customer}:{frappe.local.site}".encode()).hexdigest()
	return f"team_{digest[:12]}"


def is_untracked_user(user: str) -> bool:
	return bool(UNTRACKED_ROLES.intersection(frappe.get_roles(user)))
