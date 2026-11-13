# Copyright (c) 2026
# See license.txt

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.crm_integration import set_up_reply_webhook, sync_thread
from connect.crm_lead_owner import (
	match_team,
	owner_webhook,
	queue_consultant_owner_sync,
	record_crm_lead_owner,
	sync_lead_owner,
)
from connect.customer.doctype.customer_project.brief import send_brief
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.customer.doctype.project_quote.leads import update_lead
from connect.customer.doctype.project_quote.test_leads import make_member
from connect.partner.doctype.partner_lead.partner_lead import NotOnCRMError
from connect.partner.doctype.partner_crm_settings.partner_crm_settings import match_my_member_with_crm
from connect.team import get_my_team
from connect.partner.doctype.partner_crm_settings.test_partner_crm_settings import FakeCRM, make_crm_settings

PARTNER = "_Test Owner Sync Partner"
OWNER = "owner.sync.owner@example.test"
SALES = "owner.sync.sales@example.test"
FINANCE = "owner.sync.finance@example.test"
BUYER = "owner.sync.buyer@example.test"
OUTSIDER = "someone.on.crm@example.test"
CRM_LEAD = "CRM-LEAD-OWNER-1"


class IntegrationTestCRMLeadOwner(IntegrationTestCase):
	"""A lead's owner is the same on Connect and on the partner's CRM, either way it changes,
	and someone on only one side is named rather than guessed at."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		patch("frappe.enqueue").start()
		self.addCleanup(patch.stopall)

		make_partner(PARTNER)
		make_partner_admin(PARTNER, OWNER)
		make_member(PARTNER, SALES)
		make_member(PARTNER, FINANCE, "Finance")
		if not frappe.db.exists("Partner CRM Settings", PARTNER):
			make_crm_settings(PARTNER)
		make_buyer(BUYER, "Owner Sync Buyer Co")

		customer = frappe.db.get_value("Customer Team Member", {"user": BUYER}, "customer")
		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "Owner sync", "status": "Shared", "user": BUYER}
		).insert(ignore_permissions=True)
		project.db_set("user", BUYER)
		self.customer = customer
		self.thread = send_brief(project, customer, PARTNER)
		self.lead = frappe.db.get_value("Partner Lead", {"thread": self.thread}, "name")
		self.link(OWNER, OWNER)

	def link(self, user, crm_user):
		frappe.db.set_value("Connect Partner Member", {"partner": PARTNER, "user": user}, "crm_user", crm_user)

	def lead_doc(self):
		return frappe.get_doc("Partner Lead", self.lead)

	def on_crm_lead(self):
		frappe.db.set_value("Connect Thread", self.thread, "crm_lead_id", CRM_LEAD)

	def sync(self, crm):
		with on_crm(crm), patch.object(frappe.db, "commit"), patch.object(frappe.db, "rollback"):
			sync_thread(self.thread)

	# ---- Connect to CRM ----

	def test_a_new_crm_lead_goes_to_the_leads_owner(self):
		self.link(SALES, SALES)
		update_lead_as_owner(self.lead, SALES)
		crm = LeadsCRM()
		self.sync(crm)
		self.assertEqual(crm.posted("/api/resource/CRM Lead")[0]["lead_owner"], SALES)

	def test_assigning_the_lead_queues_its_crm_lead_owner(self):
		self.on_crm_lead()
		self.link(SALES, SALES)
		with patch("frappe.enqueue") as enqueue:
			update_lead_as_owner(self.lead, SALES)
		self.assertEqual(enqueue.call_args.args[0], "connect.crm_lead_owner.sync_lead_owner")
		self.assertEqual(enqueue.call_args.kwargs["thread"], self.thread)

	def test_the_crm_lead_goes_to_the_linked_crm_user(self):
		self.on_crm_lead()
		self.link(SALES, "sales@crm.example.test")
		update_lead_as_owner(self.lead, SALES)

		crm = FakeCRM(lead_owners={CRM_LEAD: OWNER})
		with on_crm(crm):
			sync_lead_owner(self.thread)
		self.assertIn(
			("PUT", f"/api/resource/CRM Lead/{CRM_LEAD}", {"lead_owner": "sales@crm.example.test"}), crm.calls
		)

	def test_whoever_owns_the_crm_lead_there_is_taken_off_it(self):
		# The CRM gave the Lead to someone who isn't on the team; Connect then gives it to SALES.
		self.on_crm_lead()
		self.link(SALES, SALES)
		frappe.db.set_value("Partner Lead", self.lead, "assigned_to", SALES)

		crm = FakeCRM(lead_owners={CRM_LEAD: OUTSIDER})
		with on_crm(crm):
			sync_lead_owner(self.thread)
		self.assertIn(
			{"doctype": "CRM Lead", "name": CRM_LEAD, "assign_to": OUTSIDER},
			crm.posted("/api/method/frappe.desk.form.assign_to.remove"),
		)

	def test_a_crm_lead_already_with_its_owner_is_left_alone(self):
		self.on_crm_lead()
		self.link(SALES, SALES)
		frappe.db.set_value("Partner Lead", self.lead, "assigned_to", SALES)

		crm = FakeCRM(lead_owners={CRM_LEAD: SALES})
		with on_crm(crm):
			sync_lead_owner(self.thread)
		self.assertEqual([method for method, _path, _body in crm.calls], ["GET"])

	def test_a_new_consultant_leaves_an_assigned_lead_with_its_owner(self):
		self.on_crm_lead()
		frappe.db.set_value("Partner Lead", self.lead, "assigned_to", OWNER)
		# The thread as its on_update sees it when its consultant changed.
		thread = MagicMock(partner=PARTNER)
		thread.name = self.thread
		thread.has_value_changed.return_value = True
		with patch("frappe.enqueue") as enqueue:
			queue_consultant_owner_sync(thread)
		self.assertNotIn("connect.crm_lead_owner.sync_lead_owner", [c.args[0] for c in enqueue.call_args_list])

	def test_an_owner_missing_from_the_crm_leaves_the_crm_lead_as_it_is(self):
		# Assigned before CRM sync was on, when no CRM user was needed.
		self.on_crm_lead()
		frappe.db.set_value("Partner Lead", self.lead, "assigned_to", SALES)

		crm = FakeCRM(users=[])
		with on_crm(crm):
			sync_lead_owner(self.thread)
		self.assertNotIn("PUT", [method for method, _path, _body in crm.calls])
		self.assertIn(SALES, frappe.db.get_value("Connect Thread", self.thread, "crm_sync_error"))

	def test_someone_not_on_the_crm_cannot_take_a_lead(self):
		self.assertRaises(NotOnCRMError, update_lead_as_owner, self.lead, SALES)

	# ---- CRM to Connect ----

	def test_a_crm_reassignment_to_a_team_member_moves_the_lead(self):
		self.on_crm_lead()
		with patch("frappe.enqueue") as enqueue:
			record_crm_lead_owner(PARTNER, CRM_LEAD, SALES)
		lead = self.lead_doc()
		self.assertEqual((lead.assigned_to, lead.crm_owner), (SALES, None))
		# The CRM made this change: it isn't sent back to the CRM.
		self.assertNotIn("connect.crm_lead_owner.sync_lead_owner", [c.args[0] for c in enqueue.call_args_list])
		self.assertTrue(
			frappe.db.exists("Connect Thread Member", {"thread": self.thread, "user": SALES, "is_removed": 0})
		)

	def test_a_crm_user_is_found_by_their_link(self):
		self.on_crm_lead()
		self.link(SALES, "sales@crm.example.test")
		record_crm_lead_owner(PARTNER, CRM_LEAD, "sales@crm.example.test")
		self.assertEqual(self.lead_doc().assigned_to, SALES)

	def test_a_crm_owner_off_the_team_is_noted_and_the_lead_keeps_its_owner(self):
		self.on_crm_lead()
		update_lead_as_owner(self.lead, OWNER)
		for crm_owner in (OUTSIDER, FINANCE):
			record_crm_lead_owner(PARTNER, CRM_LEAD, crm_owner)
			lead = self.lead_doc()
			self.assertEqual((lead.assigned_to, lead.crm_owner), (OWNER, crm_owner))

	def test_assigning_on_connect_clears_the_crm_note(self):
		self.on_crm_lead()
		record_crm_lead_owner(PARTNER, CRM_LEAD, OUTSIDER)
		update_lead_as_owner(self.lead, OWNER)
		self.assertIsNone(self.lead_doc().crm_owner)

	def test_a_crm_lead_connect_did_not_make_is_ignored(self):
		record_crm_lead_owner(PARTNER, "CRM-LEAD-ELSEWHERE", SALES)
		self.assertIsNone(self.lead_doc().assigned_to)

	def test_the_owner_webhook_skips_what_connect_changed(self):
		webhook = owner_webhook(PARTNER, "connect-api@crm.example.com", "secret")
		self.assertEqual((webhook["webhook_doctype"], webhook["webhook_docevent"]), ("CRM Lead", "on_change"))
		self.assertIn("doc.modified_by!='connect-api@crm.example.com'", webhook["condition"])

	def test_setting_up_sync_registers_every_webhook(self):
		crm = WebhookCRM()
		settings = frappe.get_doc("Partner CRM Settings", PARTNER)
		with patch("connect.crm_integration.crm_request", side_effect=crm):
			set_up_reply_webhook(settings)
		self.assertEqual(
			crm.webhooks,
			[
				f"Connect Reply Sync - {PARTNER}",
				f"Connect Owner Sync - {PARTNER}",
				f"Connect Lead Stage Sync - {PARTNER}",
				f"Connect Deal Stage Sync - {PARTNER}",
				f"Connect Deal Conversion Sync - {PARTNER}",
			],
		)

	# ---- Who on the team is on the CRM ----

	def test_matching_links_the_team_by_email_and_keeps_a_hand_set_link(self):
		self.link(SALES, "sales.crm@example.test")
		self.link(FINANCE, "gone@example.test")
		crm_users = [OWNER, "sales.crm@example.test"]
		with patch("connect.crm_lead_owner.crm_request", side_effect=UsersCRM(crm_users)):
			self.assertEqual(match_team(PARTNER), 2)
		linked = dict(
			frappe.get_all(
				"Connect Partner Member", filters={"partner": PARTNER}, fields=["user", "crm_user"], as_list=True
			)
		)
		self.assertEqual(
			(linked[OWNER], linked[SALES], linked[FINANCE]), (OWNER, "sales.crm@example.test", None)
		)


@contextmanager
def on_crm(crm):
	"""Every call to the partner's CRM goes to `crm`."""
	with patch("connect.crm_integration.crm_request", side_effect=crm), patch(
		"connect.crm_lead_owner.crm_request", side_effect=crm
	):
		yield


class IntegrationTestMatchFromSettings(IntegrationTestCase):
	"""Settings → Users: an owner sees who isn't on the CRM and looks them up again."""

	setUp = IntegrationTestCRMLeadOwner.setUp
	link = IntegrationTestCRMLeadOwner.link

	def member(self, user):
		return frappe.db.get_value("Connect Partner Member", {"partner": PARTNER, "user": user}, "name")

	def test_an_owner_matches_someone_added_to_the_crm(self):
		frappe.set_user(OWNER)
		self.assertFalse({row.user: row.in_crm for row in get_my_team()}[SALES])

		with patch("connect.crm_lead_owner.crm_request", side_effect=UsersCRM([SALES])):
			self.assertTrue(match_my_member_with_crm(self.member(SALES)))
		self.assertTrue({row.user: row.in_crm for row in get_my_team()}[SALES])

	def test_only_an_owner_can_match(self):
		frappe.set_user(SALES)
		self.assertRaises(frappe.PermissionError, match_my_member_with_crm, self.member(SALES))


def update_lead_as_owner(lead: str, user: str):
	frappe.set_user(OWNER)
	try:
		update_lead(lead, owner=user)
	finally:
		frappe.set_user("Administrator")


class LeadsCRM(FakeCRM):
	"""A CRM that names each new Lead in turn: CRM-LEAD-1, CRM-LEAD-2, ..."""

	def __call__(self, settings, method, path, **kwargs):
		response = super().__call__(settings, method, path, **kwargs)
		if method == "POST" and path == "/api/resource/CRM Lead":
			self.leads = getattr(self, "leads", 0) + 1
			response.json.return_value = {"data": {"name": f"CRM-LEAD-{self.leads}"}}
		return response


class UsersCRM:
	"""A CRM that only lists its users."""

	def __init__(self, emails):
		self.emails = emails

	def __call__(self, settings, method, path, **kwargs):
		response = MagicMock()
		response.json.return_value = {"data": [{"name": email, "email": email} for email in self.emails]}
		return response


class WebhookCRM:
	"""A CRM that takes new webhooks, and keeps their names."""

	def __init__(self):
		self.webhooks = []

	def __call__(self, settings, method, path, **kwargs):
		from connect.crm_integration import CRMRequestError

		response = MagicMock()
		response.json.return_value = {"message": "connect-api@crm.example.com"}
		if method == "PUT":
			raise CRMRequestError(404, "not found")
		if method == "POST":
			self.webhooks.append(kwargs["json"]["name"])
		return response
