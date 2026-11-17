# Copyright (c) 2026
# See license.txt

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime

from connect.api.auth import accept_invite
from connect.api.threads import get_thread_members
from connect.customer.doctype.customer_project.test_hiring import make_partner


def new_email(tag):
	return f"_test_invite_{tag}_{frappe.generate_hash(length=6)}@example.com".lower()


def make_user(email):
	user = {"doctype": "User", "email": email, "first_name": "Invited", "send_welcome_email": 0}
	frappe.get_doc(user).insert(ignore_permissions=True)


class IntegrationTestTeamInvitation(IntegrationTestCase):
	"""Someone added to a team is emailed a link that signs them in once, within a week. The email
	and the session are stubbed: the token is read from what would have been emailed."""

	def setUp(self):
		self.addCleanup(frappe.db.rollback)
		self.sendmail = patch("frappe.sendmail").start()
		self.login_manager = MagicMock()
		patch.object(frappe.local, "login_manager", self.login_manager, create=True).start()
		self.addCleanup(patch.stopall)
		name = f"_Test Invite Co {frappe.generate_hash(length=6)}"
		customer = frappe.get_doc({"doctype": "Customer", "customer_name": name})
		self.customer = customer.insert(ignore_permissions=True).name

	def add_member(self, email=None):
		email = email or new_email("member")
		if not frappe.db.exists("User", email):
			make_user(email)
		member = {"doctype": "Customer Team Member", "customer": self.customer, "user": email}
		return frappe.get_doc(member).insert(ignore_permissions=True)

	def token_sent(self):
		return token_in(self.sendmail)

	def test_an_added_member_is_emailed_a_link_that_signs_them_in(self):
		member = self.add_member()
		self.assertEqual(self.sendmail.call_args.kwargs["recipients"], [member.user])

		result = accept_invite(self.token_sent())

		self.login_manager.login_as.assert_called_once_with(member.user)
		self.assertTrue(result["redirect"].startswith("/connect/"))

	def test_the_link_works_once(self):
		self.add_member()
		token = self.token_sent()
		accept_invite(token)
		with self.assertRaises(frappe.ValidationError):
			accept_invite(token)

	def test_an_expired_link_is_refused(self):
		member = self.add_member()
		frappe.db.set_value(member.doctype, member.name, "invite_expires_on", add_days(now_datetime(), -1))
		with self.assertRaises(frappe.ValidationError):
			accept_invite(self.token_sent())
		self.login_manager.login_as.assert_not_called()

	def test_a_removed_members_link_is_refused(self):
		member = self.add_member()
		frappe.db.set_value(member.doctype, member.name, "is_removed", 1)
		with self.assertRaises(frappe.ValidationError):
			accept_invite(self.token_sent())

	def test_a_made_up_token_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			accept_invite("not-a-real-token")

	def test_someone_joining_their_own_company_is_not_invited(self):
		email = new_email("self")
		make_user(email)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(email)
		self.add_member(email)
		self.sendmail.assert_not_called()

	def test_a_member_added_back_is_invited_again(self):
		member = self.add_member()
		member.is_removed = 1
		member.save(ignore_permissions=True)
		self.sendmail.reset_mock()

		member.is_removed = 0
		member.save(ignore_permissions=True)

		self.assertEqual(self.sendmail.call_args.kwargs["recipients"], [member.user])


class IntegrationTestThreadInvitation(IntegrationTestCase):
	"""Someone added to a thread is emailed: a one-time sign-in link if they are new to Connect,
	else a plain link to the thread."""

	def setUp(self):
		self.addCleanup(frappe.db.rollback)
		self.sendmail = patch("frappe.sendmail").start()
		self.login_manager = MagicMock()
		patch.object(frappe.local, "login_manager", self.login_manager, create=True).start()
		self.addCleanup(patch.stopall)
		self.addCleanup(frappe.set_user, "Administrator")

		tag = frappe.generate_hash(length=6)
		customer = frappe.get_doc({"doctype": "Customer", "customer_name": f"_Test Thread Invite Co {tag}"})
		customer.insert(ignore_permissions=True)
		partner = make_partner(f"_Test Thread Invite Partner {tag}")
		self.admin = new_email("admin")
		make_user(self.admin)
		frappe.get_doc(
			{"doctype": "Customer Team Member", "customer": customer.name, "user": self.admin, "access": "Owner"}
		).insert(ignore_permissions=True)
		self.thread = frappe.get_doc(
			{"doctype": "Connect Thread", "customer": customer.name, "partner": partner}
		).insert(ignore_permissions=True)
		self.sendmail.reset_mock()

	def add_to_thread(self, email):
		frappe.set_user(self.admin)
		member, _created = self.thread.add_member(email, "Customer", "Write", self.admin)
		frappe.set_user("Administrator")
		return member

	def test_someone_new_is_emailed_a_link_that_signs_them_into_the_thread(self):
		email = new_email("new")
		self.add_to_thread(email)
		self.assertEqual(self.sendmail.call_args.kwargs["recipients"], [email])

		result = accept_invite(token_in(self.sendmail))

		self.login_manager.login_as.assert_called_once_with(email)
		self.assertEqual(result["redirect"], f"/connect/messaging?thread={self.thread.name}")

	def test_someone_who_has_signed_in_before_is_emailed_a_plain_link_to_the_thread(self):
		email = new_email("existing")
		make_user(email)
		frappe.db.set_value("User", email, "last_login", now_datetime())
		member = self.add_to_thread(email)

		link = self.sendmail.call_args.kwargs["args"]["link"]
		self.assertTrue(link.endswith(f"/connect/messaging?thread={self.thread.name}"))
		self.assertIsNone(frappe.db.get_value(member.doctype, member.name, "invite_token_hash"))

	def test_an_account_that_never_signed_in_still_gets_a_sign_in_link(self):
		email = new_email("dormant")
		make_user(email)
		self.add_to_thread(email)

		accept_invite(token_in(self.sendmail))

		self.login_manager.login_as.assert_called_once_with(email)

	def test_someone_added_shows_as_invited_until_they_first_sign_in(self):
		email = new_email("pending")
		self.add_to_thread(email)
		self.assertTrue(self.invited_flag(email))

		frappe.db.set_value("User", email, "last_login", now_datetime())

		self.assertFalse(self.invited_flag(email))

	def invited_flag(self, email):
		frappe.set_user(email)
		members = get_thread_members(self.thread.name)
		frappe.set_user("Administrator")
		return next(m for m in members if m.user == email).is_invited


def token_in(sendmail):
	link = sendmail.call_args.kwargs["args"]["link"]
	return parse_qs(urlparse(link).query)["invite"][0]
