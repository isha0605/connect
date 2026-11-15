import json
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import frappe
from frappe.tests import IntegrationTestCase

from connect.crm_integration import CRMRequestError
from connect.crm_partners import partner_payload, send_waiting_partners, sync_partner
from connect.customer.doctype.customer_project.test_hiring import make_partner

MODULE = "connect.crm_partners"
FRAPPE = "_Test CRM Partners Frappe"
PARTNER = "_Test CRM Partners Acme"
APPLYING = "_Test CRM Partners Applying"
EMAIL = "acme.partner@example.test"
SETTINGS = frappe._dict(name="_test_frappe_crm", partner=FRAPPE)
PARTNERS_PATH = "/api/resource/CRM Partner"


class PartnersCRM:
	"""Stands in for Frappe's CRM: knows the CRM Partners frappe.io made, by email, and keeps what it
	was sent."""

	def __init__(self, existing=None, down=False):
		self.existing = existing or {}
		self.down = down
		self.calls = []

	def __call__(self, settings, method, path, **kwargs):
		self.calls.append((method, unquote(path), kwargs.get("json")))
		if self.down:
			raise CRMRequestError(500, "CRM is down")

		data = {}
		if method == "GET":
			email = json.loads(kwargs["params"]["filters"])[0][2]
			data = [{"name": self.existing[email]}] if email in self.existing else []
		elif method == "POST":
			data = {"name": kwargs["json"]["name"]}
		response = MagicMock()
		response.json.return_value = {"data": data}
		return response

	def sent(self, method):
		return [(path, body) for called, path, body in self.calls if called == method]


class IntegrationTestCRMPartners(IntegrationTestCase):
	"""Each approved partner is one CRM Partner on Frappe's CRM, kept up to date by Connect."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(patch.stopall)
		self.enqueue = patch("frappe.enqueue").start()
		patch(f"{MODULE}.frappe_crm", return_value=SETTINGS).start()
		self.applying = patch(f"{MODULE}.is_applying_changes", return_value=True).start()
		patch.object(frappe.db, "commit").start()
		patch(f"{MODULE}.frappe.log_error").start()
		for partner in (FRAPPE, PARTNER):
			make_partner(partner)
		frappe.db.set_value("Partner", PARTNER, "email", EMAIL)

	def sync(self, crm, partner=PARTNER):
		with patch(f"{MODULE}.crm_request", side_effect=crm):
			sync_partner(partner)
		fields = ["frappe_crm_partner", "frappe_crm_sync_status", "frappe_crm_sync_error"]
		return frappe.db.get_value("Partner", partner, fields, as_dict=True)

	def queued(self):
		return [c for c in self.enqueue.call_args_list if c.args and c.args[0] == f"{MODULE}.sync_partner"]

	def test_the_crm_partner_frappe_io_made_is_found_by_email_and_updated(self):
		crm = PartnersCRM(existing={EMAIL: "FRAPPE-IO-ACME"})

		partner = self.sync(crm)

		self.assertEqual((partner.frappe_crm_partner, partner.frappe_crm_sync_status), ("FRAPPE-IO-ACME", "Synced"))
		path, body = crm.sent("PUT")[0]
		self.assertEqual(path, f"{PARTNERS_PATH}/FRAPPE-IO-ACME")
		self.assertEqual((body["partner_type"], body["enabled"], body["user"]), ("Gold", 1, EMAIL))
		self.assertFalse(crm.sent("POST"))

	def test_a_partner_new_to_the_crm_is_made_then_found_by_its_saved_id(self):
		crm = PartnersCRM()

		self.assertEqual(self.sync(crm).frappe_crm_partner, PARTNER)
		self.sync(crm)

		self.assertEqual(len(crm.sent("POST")), 1)
		self.assertEqual([path for path, _ in crm.sent("PUT")], [f"{PARTNERS_PATH}/{PARTNER}"])
		self.assertEqual(len(crm.sent("GET")), 1)

	def test_beginner_is_sent_as_entry(self):
		doc = frappe.get_doc("Partner", PARTNER)
		doc.tier = "Beginner"

		self.assertEqual(partner_payload(doc)["partner_type"], "Entry")

	def test_a_change_the_crm_shows_is_queued_and_others_are_not(self):
		doc = frappe.get_doc("Partner", PARTNER)
		doc.tagline = "Implementation partner"
		doc.save()
		self.assertFalse(self.queued())

		doc.tier = "Silver"
		doc.save()
		self.assertEqual(len(self.queued()), 1)
		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "frappe_crm_sync_status"), "Queued")

	def test_nothing_is_queued_while_tier_changes_are_off(self):
		self.applying.return_value = False
		doc = frappe.get_doc("Partner", PARTNER)
		doc.tier = "Silver"
		doc.save()

		self.assertFalse(self.queued())

	def test_frappe_and_partners_still_applying_are_not_sent(self):
		make_partner(APPLYING)
		frappe.db.set_value("Partner", APPLYING, "verification_status", "Pending Review")
		for partner in (FRAPPE, APPLYING):
			doc = frappe.get_doc("Partner", partner)
			doc.tier = "Silver"
			doc.save()

		self.assertFalse(self.queued())

	def test_a_partner_already_on_the_crm_is_turned_off_there(self):
		frappe.db.set_value(
			"Partner", PARTNER, {"frappe_crm_partner": "FRAPPE-IO-ACME", "verification_status": "Rejected"}
		)
		doc = frappe.get_doc("Partner", PARTNER)
		doc.enabled = 0
		doc.save()
		crm = PartnersCRM()

		self.sync(crm)

		self.assertEqual(len(self.queued()), 1)
		self.assertEqual(crm.sent("PUT")[0][1]["enabled"], 0)

	def test_a_failed_send_is_kept_and_sent_again(self):
		failed = self.sync(PartnersCRM(down=True))
		self.assertEqual(failed.frappe_crm_sync_status, "Failed")
		self.assertIn("CRM is down", failed.frappe_crm_sync_error)

		with patch(f"{MODULE}.crm_request", side_effect=PartnersCRM()):
			send_waiting_partners()

		fields = ["frappe_crm_sync_status", "frappe_crm_sync_error"]
		partner = frappe.db.get_value("Partner", PARTNER, fields, as_dict=True)
		self.assertEqual((partner.frappe_crm_sync_status, partner.frappe_crm_sync_error), ("Synced", None))

	def test_turning_tier_changes_on_queues_every_approved_partner(self):
		make_partner(APPLYING)
		frappe.db.set_value("Partner", APPLYING, "verification_status", "Pending Review")
		settings = frappe.get_single("Integration Settings")
		settings.apply_tier_and_listing_changes = 0
		settings.save()

		settings.apply_tier_and_listing_changes = 1
		settings.save()

		filters = {"name": ["in", [FRAPPE, PARTNER, APPLYING]]}
		fields = ["name", "frappe_crm_sync_status"]
		status = dict(frappe.get_all("Partner", filters=filters, fields=fields, as_list=True))
		self.assertEqual(status[PARTNER], "Queued")
		self.assertFalse(status[FRAPPE] or status[APPLYING])
		self.assertIn(f"{MODULE}.send_waiting_partners", [c.args[0] for c in self.enqueue.call_args_list if c.args])
