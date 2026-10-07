# Copyright (c) 2026
# See license.txt

import random
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.api.auth import send_code, verify_code
from connect.auth.accounts import is_own_path, landing_page
from connect.auth.email_code import EmailCode, EmailCodeError
from connect.roles import CONSULTANT_ROLE


def new_email(tag):
	return f"_test_auth_{tag}_{frappe.generate_hash(length=6)}@example.com".lower()


class IntegrationTestEmailCodeSignIn(IntegrationTestCase):
	"""The emailed-code sign-in and sign-up, with the email and the session stubbed: the code
	is read from what would have been emailed, and logging in is recorded, not done."""

	def setUp(self):
		self.sendmail = patch("frappe.sendmail").start()
		self.login_manager = MagicMock()
		patch.object(frappe.local, "login_manager", self.login_manager, create=True).start()
		patch("frappe.log_error").start()

	def tearDown(self):
		patch.stopall()

	def code_sent(self):
		"""The code in the last email, as it would be read from the inbox."""
		return self.sendmail.call_args.kwargs["args"]["code"]

	def known_user(self, email=None, enabled=1):
		email = email or new_email("known")
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Known", "enabled": enabled, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		return email

	# ---- Signing in ----

	def test_a_known_user_signs_in_with_the_code(self):
		email = self.known_user()
		send_code(email)
		result = verify_code(email, self.code_sent())
		self.login_manager.login_as.assert_called_once_with(email)
		self.assertEqual(result["user"], email)
		self.assertTrue(result["redirect"].startswith("/connect/"))

	def test_a_code_works_once(self):
		email = self.known_user()
		send_code(email)
		code = self.code_sent()
		verify_code(email, code)
		self.assertRaises(EmailCodeError, verify_code, email, code)

	def test_wrong_codes_count_down_then_lock_and_a_resend_does_not_unlock(self):
		email = self.known_user()
		send_code(email)
		code = self.code_sent()
		wrong = "000000" if code != "000000" else "111111"
		for left in (4, 3, 2, 1):
			with self.assertRaisesRegex(EmailCodeError, f"{left} left"):
				verify_code(email, wrong)
		with self.assertRaisesRegex(EmailCodeError, "Too many"):
			verify_code(email, wrong)
		with self.assertRaisesRegex(EmailCodeError, "Too many"):
			verify_code(email, code)  # even the right one, once locked
		with self.assertRaisesRegex(EmailCodeError, "Too many"):
			send_code(email)  # and asking again doesn't reset it

	def test_only_a_hash_of_the_code_is_kept_and_it_expires(self):
		email = self.known_user()
		send_code(email)
		pending = EmailCode(email).pending
		self.assertNotIn(self.code_sent(), str(pending))
		self.assertLessEqual(frappe.cache.ttl(frappe.cache.make_key(EmailCode(email).cache_key)), EmailCode.TTL_SECONDS)

	def test_an_expired_code_is_refused(self):
		email = self.known_user()
		send_code(email)
		EmailCode(email).discard()
		with self.assertRaisesRegex(EmailCodeError, "expired"):
			verify_code(email, self.code_sent())

	def test_the_code_must_be_six_digits(self):
		self.assertRaises(frappe.ValidationError, verify_code, self.known_user(), "12ab56")

	# ---- Nobody can tell who has an account ----

	def test_the_reply_is_the_same_for_known_new_and_disabled_emails(self):
		replies = {
			kind: send_code(email)["message"].replace(email, "<email>")
			for kind, email in (
				("known", self.known_user()),
				("new", new_email("new")),
				("disabled", self.known_user(enabled=0)),
			)
		}
		self.assertEqual(len(set(replies.values())), 1)

	def test_a_disabled_account_gets_a_notice_and_no_code(self):
		email = self.known_user(enabled=0)
		send_code(email)
		self.assertIsNone(EmailCode(email).pending)
		self.assertIn("disabled", self.sendmail.call_args.kwargs["subject"])

	# ---- Signing up ----

	def test_a_buyer_signs_up_with_their_company(self):
		email = new_email("buyer")
		company = f"_Test Auth Co {frappe.generate_hash(length=6)}"
		send_code(email, full_name="Meera Iyer", company_name=company, country="India")
		result = verify_code(email, self.code_sent())

		user = frappe.get_doc("User", email)
		self.assertEqual((user.full_name, user.user_type), ("Meera Iyer", "Website User"))
		self.assertEqual(frappe.db.get_value("Customer", company, "country"), "India")
		self.assertTrue(
			frappe.db.exists("Customer Team Member", {"customer": company, "user": email, "is_admin": 1})
		)
		self.login_manager.login_as.assert_called_once_with(email)
		self.assertEqual(result["user"], email)

	def test_a_new_email_on_log_in_is_asked_for_its_profile_first(self):
		email = new_email("login")
		send_code(email)
		code = self.code_sent()
		first = verify_code(email, code)
		self.assertEqual(first, {"needs_profile": True, "missing": ["full_name", "company_name"]})
		self.assertFalse(frappe.db.exists("User", email))
		self.login_manager.login_as.assert_not_called()

		company = f"_Test Auth Late Co {frappe.generate_hash(length=6)}"
		verify_code(email, code, full_name="Ravi Rao", company_name=company)  # the same code
		self.assertTrue(frappe.db.exists("Customer Team Member", {"customer": company, "user": email}))

	def test_a_partner_signs_up_without_becoming_a_customer(self):
		email = new_email("partner")
		send_code(email, full_name="Neha Shah", flow="partner")
		verify_code(email, self.code_sent())
		self.assertTrue(frappe.db.exists("User", email))
		self.assertFalse(frappe.db.exists("Customer Team Member", {"user": email}))

	def test_a_company_already_here_is_refused(self):
		company = f"_Test Auth Taken {frappe.generate_hash(length=6)}"
		frappe.get_doc({"doctype": "Customer", "customer_name": company}).insert(ignore_permissions=True)
		with self.assertRaisesRegex(frappe.ValidationError, "already registered"):
			send_code(new_email("taken"), full_name="A B", company_name=company)

	def test_sign_ups_stop_past_the_hourly_cap(self):
		email = new_email("cap")
		send_code(email, full_name="A B", company_name=f"_Test Auth Cap {frappe.generate_hash(length=6)}")
		with patch("frappe.db.get_creation_count", return_value=10_000):
			self.assertRaises(frappe.TooManyRequestsError, verify_code, email, self.code_sent())
		self.assertFalse(frappe.db.exists("User", email))

	# ---- Rate limits ----

	def test_codes_for_one_email_are_rate_limited(self):
		email = self.known_user()
		request = MagicMock(method="POST")
		with patch.object(frappe.local, "request", request, create=True), patch.object(
			frappe.local, "request_ip", f"10.0.0.{random.randint(1, 250)}", create=True
		):
			frappe.local.form_dict = frappe._dict(cmd="connect.api.auth.send_code", email=email)
			for _ in range(5):
				EmailCode(email).discard()
				send_code(email)
			self.assertRaises(frappe.RateLimitExceededError, send_code, email)
		frappe.local.form_dict = frappe._dict()

	# ---- Where people land ----

	def test_only_a_path_on_this_site_is_followed(self):
		self.assertTrue(is_own_path("/connect/starter-pack-checkout?packs=hr"))
		for path in ("//evil.example", "https://evil.example", "/\\evil.example", "", None):
			self.assertFalse(is_own_path(path))
		self.assertEqual(landing_page(self.known_user(), "/connect/compare-partners"), "/connect/compare-partners")
		self.assertNotEqual(landing_page(self.known_user(), "https://evil.example"), "https://evil.example")

	def test_a_consultant_lands_on_messaging(self):
		email = self.known_user()
		with patch("connect.auth.accounts.frappe.get_roles", return_value=[CONSULTANT_ROLE]):
			self.assertEqual(landing_page(email), "/connect/messaging")

	def test_a_buyer_lands_on_home_once_it_is_published(self):
		email = self.known_user()
		with patch("connect.auth.accounts.home_is_published", return_value=True):
			self.assertEqual(landing_page(email), "/connect/home")
		with patch("connect.auth.accounts.home_is_published", return_value=False):
			self.assertEqual(landing_page(email), "/connect/partner-directory-redesign")

	# ---- Consultants ----

	def test_someone_on_a_customer_team_cannot_be_made_a_consultant(self):
		email = new_email("guard")
		company = f"_Test Auth Guard {frappe.generate_hash(length=6)}"
		send_code(email, full_name="Asha Mehta", company_name=company)
		verify_code(email, self.code_sent())
		user = frappe.get_doc("User", email)
		user.append("roles", {"role": CONSULTANT_ROLE})
		with self.assertRaisesRegex(frappe.ValidationError, "customer"):
			user.save(ignore_permissions=True)
