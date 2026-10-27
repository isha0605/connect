# Copyright (c) 2026, Isha and Contributors
# See license.txt

import base64
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import frappe
from frappe.tests import IntegrationTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from connect.api.attachments import _copy_message_attachment
from connect.api.crm_webhook import receive_crm_reply
from connect.crm_integration import (
	CRMRequestError,
	email_body,
	queue_crm_lead_sync,
	reply_webhook,
	sync_lead_owner,
	sync_thread,
)
from connect.crm_reply import _fetch_crm_attachments, reply_author
from connect.messaging.doctype.connect_thread.connect_thread import ensure_thread_member

WEBHOOK_MODULE = "connect.api.crm_webhook"
REPLY_MODULE = "connect.crm_reply"
SYNC_MODULE = "connect.crm_integration"

BUYER = "_test_crm_buyer@example.com"
CONSULTANT_ONE = "_test_crm_consultant_one@example.com"
CONSULTANT_TWO = "_test_crm_consultant_two@example.com"

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

	def _deliver(self, communication, content="", attachments=None, failed=None, raises=False, enqueue=None):
		"""Drives the webhook the way the partner's CRM does, without a live CRM to fetch from.

		The attachment job runs inline unless `enqueue` stands in for the queue.
		"""
		fetch = (
			(lambda *a, **kw: (_ for _ in ()).throw(Exception("CRM unreachable")))
			if raises
			else (lambda *a, **kw: (attachments or [], failed or []))
		)
		original_request = getattr(frappe.local, "request", None)
		frappe.local.request = Request(
			EnvironBuilder(path="/", query_string=f"partner={self.partner}").get_environ()
		)
		try:
			with (
				patch(f"{WEBHOOK_MODULE}._verify_signature"),
				patch(f"{REPLY_MODULE}._fetch_crm_attachments", side_effect=fetch),
				patch("frappe.enqueue", side_effect=enqueue or run_job_now),
			):
				receive_crm_reply(
					reference_doctype="CRM Lead",
					reference_name="CRM-LEAD-TEST-0001",
					sent_or_received="Sent",
					content=content,
					name=communication,
				)
		finally:
			frappe.local.request = original_request
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

	def test_a_lost_attachment_is_named_as_written(self):
		# The thread shows System lines as plain text, so an escaped name would read "Q&amp;A.pdf".
		rows = self._deliver("_test_comm_5", failed=["Q&A.pdf"])
		self.assertEqual(rows[0].content, "Attachment couldn't be delivered: Q&A.pdf")

	def test_a_redelivered_failure_is_not_posted_twice(self):
		self._deliver("_test_comm_6", failed=["deck.pptx"])
		rows = self._deliver("_test_comm_6", failed=["deck.pptx"])
		self.assertEqual([r.message_type for r in rows], ["System"])

	def test_the_text_reply_does_not_wait_for_attachments(self):
		queued = MagicMock()
		rows = self._deliver("_test_comm_7", content="<p>Files to follow.</p>", enqueue=queued)
		self.assertEqual([r.message_type for r in rows], ["Text"])
		self.assertEqual(queued.call_args.kwargs["job_id"], "crm-reply-attachments::_test_comm_7")

	def test_a_reply_with_no_partner_admin_is_logged(self):
		with (
			patch(f"{REPLY_MODULE}._get_partner_admin", return_value=None),
			patch(f"{REPLY_MODULE}.frappe.log_error") as log_error,
		):
			rows = self._deliver("_test_comm_8", content="<p>Hello?</p>")
		self.assertEqual(rows, [])
		log_error.assert_called_once()

	def test_forwarding_preserves_a_small_binary_byte_for_byte(self):
		# File.get_content() text-decodes bytes that happen to be decodable, which silently grew an
		# 86-byte PNG to 103 bytes of UTF-8 on every forward.
		source = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "_test_tiny.png",
				"content": base64.b64encode(TINY_PNG).decode(),
				"decode": True,
				"is_private": 1,
			}
		).insert(ignore_permissions=True)

		copy = _copy_message_attachment(source.file_url)

		with open(copy.get_full_path(), "rb") as f:
			self.assertEqual(f.read(), TINY_PNG)


class IntegrationTestCRMSync(IntegrationTestCase):
	"""Every chat a partner has in Connect is in their CRM: a Lead owned by the chat's consultant,
	with each side's messages as emails, and replies from the CRM posted as who sent them."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		drop_fixtures()
		cls.partner = make_partner()
		cls.customer = make_customer()
		cls.admin = make_partner_admin(cls.partner)
		make_crm_settings(cls.partner)
		make_user(BUYER, "Asha", "Rao")
		frappe.get_doc(
			{"doctype": "Customer Team Member", "customer": cls.customer, "user": BUYER, "is_admin": 1}
		).insert(ignore_permissions=True)
		make_consultant(CONSULTANT_ONE, "Rahul")
		make_consultant(CONSULTANT_TWO, "Priya")
		cls.thread = (
			frappe.get_doc(
				{
					"doctype": "Connect Thread",
					"partner": cls.partner,
					"customer": cls.customer,
					"consultant": CONSULTANT_ONE,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		ensure_thread_member(cls.thread, BUYER, "Customer", BUYER)
		ensure_thread_member(cls.thread, CONSULTANT_ONE, "Partner", cls.admin)

	@classmethod
	def tearDownClass(cls):
		drop_fixtures()
		super().tearDownClass()

	def setUp(self):
		frappe.cache.delete_value(f"connect_crm_lead_source::{self.partner}::Connect Starter Pack")
		for name in frappe.get_all("Connect Message", filters={"thread": self.thread}, pluck="name"):
			frappe.delete_doc("Connect Message", name, force=True, ignore_permissions=True)
		frappe.db.set_value(
			"Connect Thread",
			self.thread,
			{
				"crm_lead_id": None,
				"crm_sync_status": None,
				"crm_sync_error": None,
				"consultant": CONSULTANT_ONE,
			},
		)

	def say(self, sender, content, message_type="Text"):
		with patch("frappe.enqueue"):
			doc = frappe.get_doc(
				{
					"doctype": "Connect Message",
					"thread": self.thread,
					"sender": sender,
					"message_type": message_type,
					"content": content,
				}
			).insert(ignore_permissions=True)
		return doc.name

	def sync(self, crm):
		with (
			patch(f"{SYNC_MODULE}.crm_request", side_effect=crm),
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback"),
			patch(f"{SYNC_MODULE}.frappe.log_error"),
		):
			sync_thread(self.thread)
		return frappe.db.get_value(
			"Connect Thread", self.thread, ["crm_lead_id", "crm_sync_status", "crm_sync_error"], as_dict=True
		)

	def test_a_message_queues_its_chat_for_the_crm(self):
		message = self.say(BUYER, "Hello")
		with patch("frappe.enqueue") as enqueue:
			queue_crm_lead_sync(frappe.get_doc("Connect Message", message))
		self.assertEqual(enqueue.call_args.args[0], "connect.crm_integration.sync_thread")
		self.assertEqual(enqueue.call_args.kwargs["thread"], self.thread)

	def test_a_new_chat_becomes_a_lead_owned_by_its_consultant(self):
		self.say(BUYER, "We just bought the pack.")
		self.say(CONSULTANT_ONE, "Welcome!\nCalls & visits soon")
		self.say(self.admin, "Rahul is now looking after this project.", message_type="System")
		crm = FakeCRM(users=[CONSULTANT_ONE])

		thread = self.sync(crm)

		lead = crm.posted("/api/resource/CRM Lead")[0]
		self.assertEqual(lead["lead_owner"], CONSULTANT_ONE)
		self.assertEqual(lead["email"], BUYER)
		self.assertEqual(lead["source"], "Connect Starter Pack")
		self.assertEqual((thread.crm_lead_id, thread.crm_sync_status), ("CRM-LEAD-NEW", "Synced"))

		# Connect's own note stays out; each side reads as it would by email.
		emails = crm.posted("/api/resource/Communication")
		self.assertEqual([e["sent_or_received"] for e in emails], ["Received", "Sent"])
		self.assertEqual(emails[0]["sender"], BUYER)
		self.assertEqual((emails[1]["sender"], emails[1]["recipients"]), (CONSULTANT_ONE, BUYER))
		self.assertEqual(emails[1]["content"], "Welcome!<br>Calls &amp; visits soon")

	def test_a_consultant_missing_from_the_crm_leaves_the_lead_for_the_sales_team(self):
		self.say(BUYER, "Hello")
		thread = self.sync(FakeCRM(users=[]))
		self.assertEqual(thread.crm_sync_status, "Synced")
		self.assertIn(CONSULTANT_ONE, thread.crm_sync_error)

	def test_a_consultant_is_found_by_their_suite_email(self):
		frappe.db.set_value("Frappe Consultant", CONSULTANT_ONE, "suite_email", "rahul@suite.example.com")
		try:
			self.say(BUYER, "Hello")
			crm = FakeCRM(users=["rahul@suite.example.com"])
			self.sync(crm)
			self.assertEqual(crm.posted("/api/resource/CRM Lead")[0]["lead_owner"], "rahul@suite.example.com")
		finally:
			frappe.db.set_value("Frappe Consultant", CONSULTANT_ONE, "suite_email", None)

	def test_each_message_is_sent_once(self):
		self.say(BUYER, "Hello")
		crm = FakeCRM(users=[CONSULTANT_ONE])
		self.sync(crm)
		self.say(BUYER, "Are you there?")
		self.sync(crm)
		self.assertEqual(
			[e["content"] for e in crm.posted("/api/resource/Communication")], ["Hello", "Are you there?"]
		)
		self.assertEqual(len(crm.posted("/api/resource/CRM Lead")), 1)

	def test_a_failed_message_is_sent_again_but_not_the_ones_before_it(self):
		self.say(BUYER, "One")
		self.say(BUYER, "Two")
		broken = FakeCRM(users=[CONSULTANT_ONE], fail_on=lambda json: json.get("content") == "Two")
		self.assertEqual(self.sync(broken).crm_sync_status, "Failed")

		crm = FakeCRM(users=[CONSULTANT_ONE])
		self.assertEqual(self.sync(crm).crm_sync_status, "Synced")
		self.assertEqual([e["content"] for e in crm.posted("/api/resource/Communication")], ["Two"])
		self.assertEqual(crm.posted("/api/resource/CRM Lead"), [])  # the Lead made before is kept

	def test_a_card_reads_as_text_in_the_crm(self):
		card = frappe.as_json(
			{"company_name": "Digitalis", "apps": ["HR and Payroll"], "timeline": "30 days"}
		)
		body = email_body(frappe._dict(message_type="Requirement", content=card))
		self.assertEqual(
			body, "<b>Requirement</b><br>Company: Digitalis<br>Timeline: 30 days<br>Apps: HR and Payroll"
		)

	def test_a_crm_reply_is_posted_as_the_consultant_who_sent_it(self):
		self.assertEqual(reply_author(self.thread, self.partner, f"Rahul <{CONSULTANT_ONE}>"), CONSULTANT_ONE)

	def test_a_crm_reply_from_someone_outside_the_chat_is_posted_as_its_consultant(self):
		# The customer's own email among them: a reply is never posted as the customer.
		for sender in ("someone@crm.example.com", BUYER, None):
			self.assertEqual(reply_author(self.thread, self.partner, sender), CONSULTANT_ONE)

	def test_a_crm_reply_in_a_chat_without_a_consultant_is_posted_as_the_partner_admin(self):
		frappe.db.set_value("Connect Thread", self.thread, "consultant", None)
		self.assertEqual(reply_author(self.thread, self.partner, "someone@crm.example.com"), self.admin)

	def test_a_new_consultant_takes_over_the_lead(self):
		frappe.db.set_value("Connect Thread", self.thread, "crm_lead_id", "CRM-LEAD-TEST-0002")
		thread = frappe.get_doc("Connect Thread", self.thread)
		thread.consultant = CONSULTANT_TWO
		with patch("frappe.enqueue") as enqueue:
			thread.save(ignore_permissions=True)
		self.assertEqual(
			enqueue.call_args.kwargs,
			{
				"queue": "short",
				"enqueue_after_commit": True,
				"thread": self.thread,
				"previous": CONSULTANT_ONE,
			},
		)

		crm = FakeCRM(users=[CONSULTANT_ONE, CONSULTANT_TWO])
		with patch(f"{SYNC_MODULE}.crm_request", side_effect=crm):
			sync_lead_owner(self.thread, previous=CONSULTANT_ONE)
		self.assertIn(
			("PUT", "/api/resource/CRM Lead/CRM-LEAD-TEST-0002", {"lead_owner": CONSULTANT_TWO}), crm.calls
		)
		self.assertIn(
			(
				"POST",
				"/api/method/frappe.desk.form.assign_to.remove",
				{"doctype": "CRM Lead", "name": "CRM-LEAD-TEST-0002", "assign_to": CONSULTANT_ONE},
			),
			crm.calls,
		)

	def test_the_reply_webhook_skips_what_connect_posted(self):
		webhook = reply_webhook("Frappe", "connect-api@crm.example.com", "secret")
		self.assertIn("doc.owner!='connect-api@crm.example.com'", webhook["condition"])
		self.assertIn("sender", [row["key"] for row in webhook["webhook_data"]])

	def test_files_on_a_crm_reply_are_fetched(self):
		crm = FakeCRM(files={"/private/files/_test_crm_reply.txt": b"hello"})
		with patch(f"{REPLY_MODULE}.crm_request", side_effect=crm):
			attachments, failed = _fetch_crm_attachments(self.partner, "_test_comm_files")
		self.assertEqual(([a["file_name"] for a in attachments], failed), (["_test_crm_reply.txt"], []))


class FakeCRM:
	"""Stands in for a partner's Frappe CRM: answers as it does, and keeps what it was sent."""

	def __init__(self, users=(), files=None, fail_on=None, industries=(), sources=None):
		self.users = users
		self.files = files or {}
		self.fail_on = fail_on
		self.industries = industries
		self.sources = sources  # None: it has every source asked for
		self.calls = []
		self.emails = 0

	def __call__(self, settings, method, path, **kwargs):
		body = kwargs.get("json")
		self.calls.append((method, path, body))
		if self.fail_on and body and self.fail_on(body):
			raise CRMRequestError(500, "CRM is down")

		response = MagicMock()
		data = {}
		doctype, _, name = unquote(path).removeprefix("/api/resource/").partition("/")
		if method == "GET" and name and doctype in ("CRM Industry", "CRM Lead Source"):
			known = self.industries if doctype == "CRM Industry" else self.sources
			if known is not None and name not in known:
				raise CRMRequestError(404, f"{doctype} {name} not found")
		elif path == "/api/resource/User":
			wanted = frappe.parse_json(kwargs["params"]["filters"])[0][2]
			data = [{"name": email, "email": email} for email in self.users if email in wanted]
		elif path == "/api/resource/CRM Lead":
			data = {"name": "CRM-LEAD-NEW"}
		elif path == "/api/resource/Communication":
			self.emails += 1
			data = {"name": f"_test_crm_email_{self.emails}"}
		elif path == "/api/resource/File":
			data = [
				{"file_name": url.rsplit("/", 1)[1], "file_url": url, "file_size": 5} for url in self.files
			]
		elif path in self.files:
			response.content = self.files[path]
		response.json.return_value = {"data": data}
		return response

	def posted(self, path):
		return [body for method, called, body in self.calls if method == "POST" and called == path]


def make_user(email, first_name, last_name=None):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first_name,
				"last_name": last_name,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)


def make_consultant(email, first_name):
	"""A Frappe Consultant without what joining the team does, which needs the real Frappe partner.
	Left disabled: an enabled one without the role would have the User hook queue a job to fix it."""
	make_user(email, first_name)
	if not frappe.db.exists("Frappe Consultant", email):
		frappe.get_doc(
			{"doctype": "Frappe Consultant", "user": email, "full_name": first_name, "enabled": 0}
		).db_insert()


def run_job_now(method, **kwargs):
	for option in ("queue", "job_id", "deduplicate", "enqueue_after_commit"):
		kwargs.pop(option, None)
	method(**kwargs)


def make_partner():
	return (
		frappe.get_doc(
			{
				"doctype": "Partner",
				"partner_name": "_test_crm_partner",
				"tier": "Gold",
				"country": "India",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def make_customer():
	return (
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "_test_crm_customer",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def make_partner_admin(partner):
	user = (
		frappe.get_doc(
			{
				"doctype": "User",
				"email": "_test_crm_admin@example.com",
				"first_name": "CRM",
				"send_welcome_email": 0,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)
	frappe.get_doc(
		{
			"doctype": "Connect Partner Member",
			"partner": partner,
			"user": user,
			"is_admin": 1,
		}
	).insert(ignore_permissions=True)
	return user


def make_thread(partner, customer):
	return (
		frappe.get_doc(
			{
				"doctype": "Connect Thread",
				"partner": partner,
				"customer": customer,
				"crm_lead_id": "CRM-LEAD-TEST-0001",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def make_crm_settings(partner):
	return (
		frappe.get_doc(
			{
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
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


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
		("Connect Message", {"thread": ["in", _test_threads() or [""]]}),
		("File", {"file_name": ["like", "\\_test\\_tiny%"]}),
		("File", {"file_name": "_test_crm_reply.txt"}),
		("Connect Thread Member", {"thread": ["in", _test_threads() or [""]]}),
		("Connect Thread", {"partner": "_test_crm_partner"}),
		("Partner CRM Settings", {"partner": "_test_crm_partner"}),
		("Connect Partner Member", {"partner": "_test_crm_partner"}),
		("Partner", {"name": "_test_crm_partner"}),
		("Customer Team Member", {"customer": "_test_crm_customer"}),
		("Customer", {"name": "_test_crm_customer"}),
		("Frappe Consultant", {"name": ["in", [CONSULTANT_ONE, CONSULTANT_TWO]]}),
		("User", {"name": ["in", ["_test_crm_admin@example.com", BUYER, CONSULTANT_ONE, CONSULTANT_TWO]]}),
	):
		for name in frappe.get_all(doctype, filters=filters, pluck="name"):
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, ignore_on_trash=True)
	frappe.db.commit()
