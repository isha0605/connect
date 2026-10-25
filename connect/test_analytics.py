from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from connect.analytics import capture, get_browser_config, link_visitor, record_signup, team_id
from connect.roles import CONSULTANT_ROLE, CUSTOMER_ROLE, PARTNER_ROLE

PULSE_CONFIG = {
	"enabled": True,
	"host": "https://pulse.example.com",
	"client_url": "https://pulse.example.com/assets/pulse/js/pulse_client.js",
	"key": "public-key",
}
VISITOR = "anon_" + "a" * 32


def as_user(roles: list[str], customer: str | None = None):
	"""Patches who the analytics module thinks the user is."""
	return (
		patch("connect.analytics.frappe.get_roles", return_value=roles),
		patch("connect.analytics.get_customer_for_user", return_value=customer),
	)


def browser_config(roles: list[str], client_url: str | None = None, customer: str | None = None) -> dict:
	roles_patch, customer_patch = as_user(roles, customer)
	with (
		roles_patch,
		customer_patch,
		patch("connect.analytics.pulse.boot_config", return_value=dict(PULSE_CONFIG)),
		patch.dict(frappe.local.conf, {"pulse_client_url": client_url}),
	):
		return get_browser_config()


def captured(user: str, roles: list[str], customer: str | None = None):
	"""The call `capture` makes to Pulse for `user`, or None when it sends nothing."""
	roles_patch, customer_patch = as_user(roles, customer)
	with (
		roles_patch,
		customer_patch,
		patch.dict(frappe.flags, {"in_test": False}),
		patch("connect.analytics.pulse.capture") as pulse_capture,
	):
		capture("order_placed", user, {"packs": "core"})
	return pulse_capture.call_args


class TestBrowserConfig(UnitTestCase):
	def test_guests_and_customers_are_tracked(self):
		self.assertTrue(browser_config(["Guest"])["enabled"])
		self.assertTrue(browser_config([CUSTOMER_ROLE])["enabled"])

	def test_partners_and_staff_are_not_tracked(self):
		for role in (PARTNER_ROLE, CONSULTANT_ROLE, "System Manager"):
			self.assertEqual(browser_config([CUSTOMER_ROLE, role]), {"enabled": False})

	def test_a_customer_carries_their_team(self):
		self.assertIsNone(browser_config(["Guest"])["team"])
		self.assertEqual(browser_config([CUSTOMER_ROLE], customer="CUST-1")["team"], team_id("CUST-1"))

	def test_client_url_follows_site_config(self):
		self.assertEqual(browser_config(["Guest"])["client_url"], PULSE_CONFIG["client_url"])
		local = "/assets/pulse/js/pulse_client.js"
		self.assertEqual(browser_config(["Guest"], client_url=local)["client_url"], local)

	def test_disabled_telemetry_passes_through(self):
		with (
			patch("connect.analytics.frappe.get_roles", return_value=["Guest"]),
			patch("connect.analytics.pulse.boot_config", return_value={"enabled": False}),
		):
			self.assertEqual(get_browser_config(), {"enabled": False})


class TestCapture(UnitTestCase):
	def test_a_customer_event_goes_to_their_team(self):
		call = captured("buyer@example.com", [CUSTOMER_ROLE], customer="CUST-1")
		self.assertEqual(call.args, ("order_placed", "connect"))
		self.assertEqual(call.kwargs["team"], team_id("CUST-1"))

	def test_guests_partners_and_staff_send_nothing(self):
		self.assertIsNone(captured("Guest", ["Guest"]))
		self.assertIsNone(captured("partner@example.com", [PARTNER_ROLE]))
		self.assertIsNone(captured("Administrator", ["System Manager"]))

	def test_team_ids_hide_the_customer(self):
		self.assertRegex(team_id("Acme Pvt Ltd"), r"^team_[0-9a-f]{12}$")
		self.assertNotEqual(team_id("Acme Pvt Ltd"), team_id("Other Co"))


class TestRecordSignup(UnitTestCase):
	def signup(self, visitor_id: str | None):
		roles_patch, customer_patch = as_user([CUSTOMER_ROLE], customer="CUST-1")
		with (
			roles_patch,
			customer_patch,
			patch.dict(frappe.flags, {"in_test": False}),
			patch("connect.analytics.pulse.is_enabled", return_value=True),
			patch("connect.analytics.pulse.capture") as pulse_capture,
			patch("connect.analytics.frappe.enqueue") as enqueue,
		):
			record_signup("buyer@example.com", "India", visitor_id)
		return pulse_capture, enqueue

	def test_signup_links_the_visit_before_it(self):
		pulse_capture, enqueue = self.signup(VISITOR)
		self.assertEqual(pulse_capture.call_args.args[0], "signup_completed")
		enqueue.assert_called_once_with(
			link_visitor, visitor_id=VISITOR, team=team_id("CUST-1"), enqueue_after_commit=True
		)

	def test_only_a_pulse_visitor_id_is_linked(self):
		for visitor_id in (None, "", "user_abc", "team_abc", "anon_not-hex"):
			_, enqueue = self.signup(visitor_id)
			enqueue.assert_not_called()
