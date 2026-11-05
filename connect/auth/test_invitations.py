# Copyright (c) 2026
# See license.txt

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime

from connect.api.auth import accept_invite


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
		link = self.sendmail.call_args.kwargs["args"]["link"]
		return parse_qs(urlparse(link).query)["invite"][0]

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
