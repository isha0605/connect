# Copyright (c) 2026, Isha and Contributors
# See license.txt

import base64
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from connect.api.attachments import _copy_message_attachment
from connect.api.crm_webhook import receive_crm_reply

WEBHOOK_MODULE = "connect.api.crm_webhook"

# Small enough to decode cleanly as windows-1250, which is exactly what used to corrupt it.
TINY_PNG = base64.b64decode(
	"iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQMAAAD+wSzIAAAABlBMVEX/AAD///9BHTQRAAAADUlEQVQI12P4/x8AAwAB/2E5LtQAAAAASUVORK5CYII="
)

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = ["Customer", "Partner", "User"]


class IntegrationTestPartnerCRMSettings(IntegrationTestCase):
	"""A partner replying from their CRM is the one path into a thread nobody in Connect can retry."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Fixtures live for the whole class: this suite's records are not rolled back between tests,
		# so re-creating them per test collides on Partner/Customer's name-from-field autonaming.
		drop_fixtures()
		cls.partner = make_partner()
		cls.customer = make_customer()
		cls.admin = make_partner_admin(cls.partner)
		cls.thread = make_thread(cls.partner, cls.customer)
		make_crm_settings(cls.partner)

	@classmethod
	def tearDownClass(cls):
		drop_fixtures()
		super().tearDownClass()

	def setUp(self):
		# Each test replays a delivery, and receive_crm_reply drops one whose Communication it has
		# already synced — so last test's messages have to go before the next one runs.
		drop_test_messages()

	def _deliver(self, communication, content="", attachments=None, failed=None, raises=False):
		"""Drives the webhook the way the partner's CRM does, without a live CRM to fetch from."""
		fetch = (
			(lambda *a, **kw: (_ for _ in ()).throw(Exception("CRM unreachable")))
			if raises
			else (lambda *a, **kw: (attachments or [], failed or []))
		)
		frappe.local.request = Request(
			EnvironBuilder(path="/", query_string=f"partner={self.partner}").get_environ()
		)
		with (
			patch(f"{WEBHOOK_MODULE}._verify_signature"),
			patch(f"{WEBHOOK_MODULE}._fetch_crm_attachments", side_effect=fetch),
		):
			receive_crm_reply(
				reference_doctype="CRM Lead",
				reference_name="CRM-LEAD-TEST-0001",
				sent_or_received="Sent",
				content=content,
				name=communication,
			)
		return frappe.get_all(
			"Connect Message",
			filters={"crm_source_communication": communication},
			fields=["name", "message_type", "content"],
			order_by="creation",
		)

	def test_a_lost_attachment_is_named_in_the_thread(self):
		rows = self._deliver("_test_comm_1", content="<p>Here it is.</p>", failed=["report.pdf"])
		self.assertEqual([r.message_type for r in rows], ["Text", "System"])
		self.assertIn("report.pdf", rows[1].content)

	def test_a_media_only_reply_that_fails_still_reaches_the_thread(self):
		# No text to fall back on: without the System line the reply vanishes with no trace at all.
		rows = self._deliver("_test_comm_2", content="", failed=["deck.pptx"])
		self.assertEqual([r.message_type for r in rows], ["System"])
		self.assertIn("deck.pptx", rows[0].content)

	def test_a_broken_crm_does_not_cost_the_partner_their_text_reply(self):
		rows = self._deliver("_test_comm_3", content="<p>Call me.</p>", raises=True)
		self.assertEqual([r.message_type for r in rows], ["Text"])
		self.assertEqual(rows[0].content, "Call me.")

	def test_a_reply_with_nothing_in_it_is_not_posted(self):
		self.assertEqual(self._deliver("_test_comm_4", content=""), [])

	def test_forwarding_preserves_a_small_binary_byte_for_byte(self):
		# File.get_content() text-decodes bytes that happen to be decodable, which silently grew an
		# 86-byte PNG to 103 bytes of UTF-8 on every forward.
		source = frappe.get_doc({
			"doctype": "File",
			"file_name": "_test_tiny.png",
			"content": base64.b64encode(TINY_PNG).decode(),
			"decode": True,
			"is_private": 1,
		}).insert(ignore_permissions=True)

		copy = _copy_message_attachment(source.file_url)

		with open(copy.get_full_path(), "rb") as f:
			self.assertEqual(f.read(), TINY_PNG)


def make_partner():
	return frappe.get_doc({
		"doctype": "Partner",
		"partner_name": "_test_crm_partner",
		"tier": "Gold",
		"country": "India",
	}).insert(ignore_permissions=True).name


def make_customer():
	return frappe.get_doc({
		"doctype": "Customer",
		"customer_name": "_test_crm_customer",
	}).insert(ignore_permissions=True).name


def make_partner_admin(partner):
	user = frappe.get_doc({
		"doctype": "User",
		"email": "_test_crm_admin@example.com",
		"first_name": "CRM",
		"send_welcome_email": 0,
	}).insert(ignore_permissions=True).name
	frappe.get_doc({
		"doctype": "Connect Partner Member",
		"partner": partner,
		"user": user,
		"is_admin": 1,
	}).insert(ignore_permissions=True)
	return user


def make_thread(partner, customer):
	return frappe.get_doc({
		"doctype": "Connect Thread",
		"partner": partner,
		"customer": customer,
		"crm_lead_id": "CRM-LEAD-TEST-0001",
	}).insert(ignore_permissions=True).name


def make_crm_settings(partner):
	return frappe.get_doc({
		"doctype": "Partner CRM Settings",
		"partner": partner,
		"crm_type": "Frappe CRM",
		"enabled": 1,
		"site_url": "http://crm.example.com",
		"api_key": "_test_key",
		"api_secret": "_test_secret",
		"default_lead_status": "New",
		# Pre-set so on_update's sync_reply_webhook short-circuits instead of trying to register a
		# webhook against the fake CRM host and stalling the suite on a real HTTP timeout.
		"crm_reply_webhook_id": "_test_webhook",
	}).insert(ignore_permissions=True).name


def drop_test_messages():
	for name in frappe.get_all(
		"Connect Message", filters={"crm_source_communication": ["like", "\\_test\\_comm%"]}, pluck="name"
	):
		frappe.delete_doc("Connect Message", name, force=True, ignore_permissions=True)


def _test_threads():
	return frappe.get_all("Connect Thread", filters={"partner": "_test_crm_partner"}, pluck="name")


def drop_fixtures():
	"""Deletes leaf-first so link validation can't block the parents."""
	drop_test_messages()
	for doctype, filters in (
		("File", {"file_name": ["like", "\\_test\\_tiny%"]}),
		("Connect Thread Member", {"thread": ["in", _test_threads() or [""]]}),
		("Connect Thread", {"partner": "_test_crm_partner"}),
		("Partner CRM Settings", {"partner": "_test_crm_partner"}),
		("Connect Partner Member", {"partner": "_test_crm_partner"}),
		("Partner", {"name": "_test_crm_partner"}),
		("Customer", {"name": "_test_crm_customer"}),
		("User", {"name": "_test_crm_admin@example.com"}),
	):
		for name in frappe.get_all(doctype, filters=filters, pluck="name"):
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, ignore_on_trash=True)
	frappe.db.commit()
