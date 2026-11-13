# Copyright (c) 2026, Isha and contributors
# See license.txt

from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import frappe
from frappe.tests import IntegrationTestCase

from connect.crm_integration import CRMRequestError
from connect.crm_stage_sync import (
	CONVERT_TO_DEAL,
	CRM_DEAL,
	CRM_LEAD,
	queue_stage_sync,
	record_crm_status,
	refresh_status_map,
	stage_webhooks,
	sync_stage,
)
from connect.customer.doctype.customer_project.brief import send_brief
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.partner.doctype.partner_crm_settings.partner_crm_settings import save_my_settings
from connect.partner.doctype.partner_crm_settings.test_partner_crm_settings import make_crm_settings

PARTNER = "_Test Stage Sync Partner"
OWNER = "stage.sync.owner@example.test"
BUYER = "stage.sync.buyer@example.test"
CRM_LEAD_ID = "CRM-LEAD-STAGE-1"
CRM_DEAL_ID = "CRM-DEAL-STAGE-1"
SETTINGS_MODULE = "connect.partner.doctype.partner_crm_settings.partner_crm_settings"

# Cold has no default and no Connect stage by its name.
LEAD_STATUSES = ["New", "Contacted", "Nurture", "Qualified", "Unqualified", "Junk", "Cold"]
DEAL_STATUSES = {"Qualification": "Open", "Negotiation": "Ongoing", "Won": "Won", "Lost": "Lost"}


class StatusCRM:
	"""Stands in for a partner's Frappe CRM: its statuses, lost reasons and conversion."""

	def __init__(self, lost_reasons=("Other", "Competition")):
		self.lost_reasons = lost_reasons
		self.calls = []

	def __call__(self, settings, method, path, **kwargs):
		self.calls.append((method, unquote(path), kwargs.get("json")))
		response = MagicMock()
		doctype, _, name = unquote(path).removeprefix("/api/resource/").partition("/")
		body = {"data": {}}
		if doctype == "CRM Lead Status":
			body = {"data": [{"name": status} for status in LEAD_STATUSES]}
		elif doctype == "CRM Deal Status" and not name:
			body = {"data": [{"name": status} for status in DEAL_STATUSES]}
		elif doctype == "CRM Deal Status":
			body = {"data": {"name": name, "type": DEAL_STATUSES[name]}}
		elif doctype == "CRM Lost Reason" and name not in self.lost_reasons:
			raise CRMRequestError(404, "not found")
		elif path == CONVERT_TO_DEAL:
			body = {"message": CRM_DEAL_ID}
		response.json.return_value = body
		return response

	def sent(self, method, prefix):
		return [(path, body) for verb, path, body in self.calls if verb == method and path.startswith(prefix)]


@contextmanager
def on_crm(crm):
	with patch("connect.crm_stage_sync.crm_request", side_effect=crm):
		yield


class IntegrationTestCRMStageSync(IntegrationTestCase):
	"""A lead's stage is the same on Connect and on the partner's CRM, through the statuses the
	partner matched to stages; a Lead becomes a Deal when only a Deal status matches."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		patch("frappe.enqueue").start()
		# Loading the map the first time sets the webhooks up on the CRM; that has its own tests.
		patch("connect.crm_integration.set_up_reply_webhook").start()
		# The fake CRM's address doesn't resolve; refresh_status_map is called with a fake below.
		patch(f"{SETTINGS_MODULE}.PartnerCRMSettings.check_crm_connection").start()
		self.addCleanup(patch.stopall)

		make_partner(PARTNER)
		make_partner_admin(PARTNER, OWNER)
		if not frappe.db.exists("Partner CRM Settings", PARTNER):
			make_crm_settings(PARTNER)
		self.settings = frappe.get_doc("Partner CRM Settings", PARTNER)
		with on_crm(StatusCRM()):
			refresh_status_map(self.settings, self.settings)
		self.match({("CRM Lead", "Contacted"): "Follow Up", ("CRM Lead", "Nurture"): "Follow Up",
			("CRM Lead", "Unqualified"): "Lost"})
		self.settings.save(ignore_permissions=True)

		make_buyer(BUYER, "Stage Sync Buyer Co")
		customer = frappe.db.get_value("Customer Team Member", {"user": BUYER}, "customer")
		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "Stage sync", "status": "Shared", "user": BUYER}
		).insert(ignore_permissions=True)
		project.db_set("user", BUYER)
		self.thread = send_brief(project, customer, PARTNER)
		frappe.db.set_value("Connect Thread", self.thread, "crm_lead_id", CRM_LEAD_ID)
		self.lead = frappe.db.get_value("Partner Lead", {"thread": self.thread}, "name")

	def match(self, stages):
		for row in self.settings.status_map:
			key = (row.crm_doctype, row.crm_status)
			if key in stages:
				row.stage = stages[key]

	def move(self, stage, lost_reason=None):
		frappe.db.set_value("Partner Lead", self.lead, {"stage": stage, "lost_reason": lost_reason})
		crm = StatusCRM()
		with on_crm(crm):
			sync_stage(self.lead)
		return crm

	def lead_doc(self):
		return frappe.get_doc("Partner Lead", self.lead)

	# ---- The map ----

	def test_the_map_lists_the_crms_statuses_on_their_default_stages(self):
		stages = {(row.crm_doctype, row.crm_status): row.stage for row in self.settings.status_map}
		self.assertEqual(len(stages), len(LEAD_STATUSES) + len(DEAL_STATUSES))
		# a CRM Status Default, else the stage with the status's own name, else none to pick
		self.assertEqual(stages[(CRM_LEAD, "New")], "Open")
		self.assertEqual(stages[(CRM_LEAD, "Junk")], "Junk")
		self.assertEqual(stages[(CRM_DEAL, "Negotiation")], "Negotiation")
		self.assertFalse(stages[(CRM_LEAD, "Cold")])

	def test_reading_the_crm_again_keeps_what_the_partner_picked(self):
		self.match({(CRM_LEAD, "Junk"): None})
		with on_crm(StatusCRM()):
			refresh_status_map(self.settings, self.settings)
		stages = {(row.crm_doctype, row.crm_status): row.stage for row in self.settings.status_map}
		self.assertEqual(stages[(CRM_LEAD, "Contacted")], "Follow Up")
		self.assertFalse(stages[(CRM_LEAD, "Junk")])

	def test_a_stage_connect_doesnt_have_is_refused(self):
		self.settings.status_map[0].stage = "Hot"
		self.assertRaises(frappe.ValidationError, self.settings.save, ignore_permissions=True)

	# ---- Connect to CRM ----

	def test_a_lead_stage_sets_the_crm_leads_status(self):
		crm = self.move("Follow Up")
		# Contacted and Nurture both match Follow Up: the first in the CRM's order is sent.
		self.assertEqual(crm.sent("PUT", "/api/resource/CRM Lead/"), [(f"/api/resource/CRM Lead/{CRM_LEAD_ID}", {"status": "Contacted"})])
		self.assertFalse(crm.sent("POST", CONVERT_TO_DEAL))

	def test_a_deal_stage_converts_the_crm_lead_first(self):
		crm = self.move("Negotiation")
		self.assertEqual(crm.sent("POST", CONVERT_TO_DEAL), [(CONVERT_TO_DEAL, {"lead": CRM_LEAD_ID})])
		self.assertEqual(crm.sent("PUT", "/api/resource/CRM Deal/")[0][1], {"status": "Negotiation"})
		self.assertEqual(frappe.db.get_value("Connect Thread", self.thread, "crm_deal_id"), CRM_DEAL_ID)

		# Once a Deal, it is converted only once.
		crm = self.move("Qualification")
		self.assertFalse(crm.sent("POST", CONVERT_TO_DEAL))
		self.assertEqual(crm.sent("PUT", "/api/resource/CRM Deal/"), [(f"/api/resource/CRM Deal/{CRM_DEAL_ID}", {"status": "Qualification"})])

	def test_a_lost_deal_says_why(self):
		frappe.db.set_value("Connect Thread", self.thread, "crm_deal_id", CRM_DEAL_ID)
		# The CRM has no "No budget" reason, so Other carries it as a note.
		crm = self.move("Lost", "No budget")
		self.assertEqual(
			crm.sent("PUT", "/api/resource/CRM Deal/")[0][1],
			{"status": "Lost", "lost_reason": "Other", "lost_notes": "No budget"},
		)
		crm = self.move("Lost", "Lost to competitor")
		self.assertEqual(crm.sent("PUT", "/api/resource/CRM Deal/")[0][1]["lost_reason"], "Other")

	def test_a_still_open_lead_lost_is_unqualified_on_the_crm(self):
		crm = self.move("Lost", "No budget")
		self.assertEqual(crm.sent("PUT", "/api/resource/CRM Lead/")[0][1], {"status": "Unqualified"})
		self.assertFalse(crm.sent("POST", CONVERT_TO_DEAL))

	def test_an_unmatched_stage_is_noted_on_the_lead_and_cleared_once_one_syncs(self):
		crm = self.move("Closed")
		self.assertFalse(crm.sent("PUT", "/api/resource/"))
		self.assertIn("Closed", self.lead_doc().crm_stage_note)

		self.move("Follow Up")
		self.assertFalse(self.lead_doc().crm_stage_note)

	def test_a_stage_from_the_crm_isnt_sent_back(self):
		doc = self.lead_doc()
		doc.stage = "Follow Up"
		doc.flags.from_crm = True
		with patch("connect.crm_stage_sync.queue_stage_sync") as queue:
			doc.save(ignore_permissions=True)
		queue.assert_not_called()

	def test_a_lead_without_a_crm_lead_has_nothing_to_send(self):
		frappe.db.set_value("Connect Thread", self.thread, "crm_lead_id", None)
		with patch("frappe.enqueue") as enqueue:
			queue_stage_sync(self.lead_doc())
		enqueue.assert_not_called()

	# ---- CRM to Connect ----

	def test_a_crm_lead_status_moves_the_lead(self):
		record_crm_status(PARTNER, CRM_LEAD, CRM_LEAD_ID, "Nurture")
		self.assertEqual(self.lead_doc().stage, "Follow Up")

	def test_a_crm_lost_reason_connect_doesnt_have_becomes_other(self):
		record_crm_status(PARTNER, CRM_LEAD, CRM_LEAD_ID, "Unqualified")
		self.assertEqual((self.lead_doc().stage, self.lead_doc().lost_reason), ("Lost", "Other"))

	def test_a_deal_made_on_the_crm_is_remembered_and_followed(self):
		record_crm_status(PARTNER, CRM_DEAL, CRM_DEAL_ID, "Qualification", crm_lead=CRM_LEAD_ID)
		self.assertEqual(frappe.db.get_value("Connect Thread", self.thread, "crm_deal_id"), CRM_DEAL_ID)
		self.assertEqual(self.lead_doc().stage, "Qualification")

		record_crm_status(PARTNER, CRM_DEAL, CRM_DEAL_ID, "Lost", lost_reason="Lost to competitor")
		self.assertEqual((self.lead_doc().stage, self.lead_doc().lost_reason), ("Lost", "Lost to competitor"))

	def test_won_on_the_crm_doesnt_win_the_lead(self):
		record_crm_status(PARTNER, CRM_DEAL, CRM_DEAL_ID, "Won", crm_lead=CRM_LEAD_ID)
		self.assertEqual(self.lead_doc().stage, "Open")

	def test_a_won_lead_stays_won(self):
		frappe.db.set_value("Partner Lead", self.lead, "stage", "Won")
		record_crm_status(PARTNER, CRM_LEAD, CRM_LEAD_ID, "Unqualified")
		self.assertEqual(self.lead_doc().stage, "Won")

	def test_an_unmatched_or_unknown_crm_status_changes_nothing(self):
		record_crm_status(PARTNER, CRM_LEAD, CRM_LEAD_ID, "Cold")  # matched to no stage
		record_crm_status(PARTNER, CRM_LEAD, "CRM-LEAD-NOT-OURS", "Nurture")
		self.assertEqual(self.lead_doc().stage, "Open")

	def test_status_webhooks_send_every_change_and_conversion_skips_connects_own(self):
		# The partner's CRM user may be the API user Connect signs in as: their changes must come.
		webhooks = stage_webhooks(PARTNER, "connect@crm.example.com", "secret")
		self.assertEqual([w["webhook_doctype"] for w in webhooks], [CRM_LEAD, CRM_DEAL, CRM_DEAL])
		self.assertEqual([("connect@crm.example.com" in w["condition"]) for w in webhooks], [False, False, True])
		self.assertTrue(all(w["webhook_secret"] == "secret" for w in webhooks))

	def test_connects_own_change_coming_back_changes_nothing(self):
		self.move("Follow Up")  # Connect sends Contacted
		record_crm_status(PARTNER, CRM_LEAD, CRM_LEAD_ID, "Contacted")
		self.assertEqual(self.lead_doc().stage, "Follow Up")

	# ---- Settings ----

	def test_the_partner_saves_their_stage_choices(self):
		frappe.set_user(OWNER)
		choices = [{"crm_doctype": CRM_LEAD, "crm_status": "New", "stage": "Open"}]
		saved = save_my_settings("http://crm.example.com", "_test_key", "New", status_map=frappe.as_json(choices))
		new = next(row for row in saved["status_map"] if row["crm_status"] == "New")
		self.assertEqual(new["stage"], "Open")
		self.assertIn("Negotiation", saved["stages"])
