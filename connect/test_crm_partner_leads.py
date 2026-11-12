from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.crm_integration import CRMRequestError
from connect.crm_partner_leads import send_to_frappe_crm, sync_customer_lead
from connect.customer.doctype.customer_project.brief import send_brief
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.partner.doctype.partner_crm_settings.test_partner_crm_settings import FakeCRM

MODULE = "connect.crm_partner_leads"
FRAPPE = "_Test CRM Frappe Partner"
PARTNER = "_Test CRM Lead Partner"
OTHER_PARTNER = "_Test CRM Lead Other Partner"
BUYER = "crm.lead.buyer@example.test"
COMPANY = "CRM Lead Buyer Co"
SETTINGS = frappe._dict(name="_test_frappe_crm", partner=FRAPPE, default_lead_status="New")


class NotesCRM(FakeCRM):
	"""The fake CRM, also answering for notes: each new note gets a name, and `missing` notes are gone."""

	def __init__(self, missing=(), **kwargs):
		super().__init__(**kwargs)
		self.missing = missing
		self.notes = 0

	def __call__(self, settings, method, path, **kwargs):
		if method == "PUT" and path.rsplit("/", 1)[-1] in self.missing:
			self.calls.append((method, path, kwargs.get("json")))
			raise CRMRequestError(404, "FCRM Note not found")
		response = super().__call__(settings, method, path, **kwargs)
		if method == "POST" and path == "/api/resource/FCRM Note":
			self.notes += 1
			response.json.return_value = {"data": {"name": f"NOTE-{self.notes}"}}
		return response

	def put(self, path):
		return [body for method, called, body in self.calls if method == "PUT" and called == path]


class IntegrationTestPartnerLeadsInFrappeCRM(IntegrationTestCase):
	"""Each customer partners work is one Lead on Frappe's sales CRM, with a note per partner."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enqueue = patch("frappe.enqueue").start()
		patch(f"{MODULE}.frappe_crm", return_value=None).start()
		self.addCleanup(patch.stopall)
		for partner in (FRAPPE, PARTNER, OTHER_PARTNER):
			make_partner(partner)
			make_partner_admin(partner, f"{frappe.scrub(partner)}@example.test")
		make_buyer(BUYER, COMPANY)
		self.customer = frappe.db.get_value("Customer Team Member", {"user": BUYER}, "customer")

	def send(self, partner, project_name="Batch tracking"):
		"""The buyer sends the partner a brief; returns its Partner Lead."""
		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": project_name, "status": "Shared", "user": BUYER}
		).insert(ignore_permissions=True)
		send_brief(project, self.customer, partner)
		return frappe.db.get_value("Project Quote", {"customer_project": project.name}, "lead")

	def sync(self, crm):
		with (
			patch(f"{MODULE}.frappe_crm", return_value=SETTINGS),
			patch(f"{MODULE}.crm_request", side_effect=crm),
			patch("connect.crm_integration.crm_request", side_effect=crm),
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback"),
			patch(f"{MODULE}.frappe.log_error"),
		):
			sync_customer_lead(self.customer)
		return frappe.db.get_value(
			"Customer", self.customer, ["frappe_crm_lead", "frappe_crm_sync_status"], as_dict=True
		)

	def queued_customers(self):
		return [call.kwargs.get("customer") for call in self.enqueue.call_args_list if call.kwargs.get("customer")]

	def test_a_partners_brief_is_queued_and_frappes_own_leads_are_left_out(self):
		with patch(f"{MODULE}.frappe_crm", return_value=SETTINGS):
			self.send(FRAPPE)
			self.assertEqual(self.queued_customers(), [])

			self.send(PARTNER)
		self.assertIn(self.customer, self.queued_customers())
		self.assertEqual(frappe.db.get_value("Customer", self.customer, "frappe_crm_sync_status"), "Queued")

	def test_one_lead_for_the_customer_with_a_note_per_partner(self):
		first = self.send(PARTNER, "Batch tracking")
		second = self.send(OTHER_PARTNER, "Payroll")
		self.send(FRAPPE, "Starter Pack")
		crm = NotesCRM()

		self.assertEqual(self.sync(crm), {"frappe_crm_lead": "CRM-LEAD-NEW", "frappe_crm_sync_status": "Synced"})

		[lead] = crm.posted("/api/resource/CRM Lead")
		self.assertEqual((lead["organization"], lead["email"]), (COMPANY, BUYER))
		self.assertEqual((lead["source"], lead["status"]), ("Connect Partner Lead", "New"))
		notes = crm.posted("/api/resource/FCRM Note")
		self.assertEqual([note["title"] for note in notes], [PARTNER, OTHER_PARTNER])
		self.assertEqual({note["reference_docname"] for note in notes}, {"CRM-LEAD-NEW"})
		self.assertIn("Batch tracking: Awaiting", notes[0]["content"])
		self.assertEqual(frappe.db.get_value("Partner Lead", first, "frappe_crm_note"), "NOTE-1")
		self.assertEqual(frappe.db.get_value("Partner Lead", second, "frappe_crm_note"), "NOTE-2")

	def test_a_partners_progress_updates_its_note_in_place(self):
		lead = self.send(PARTNER)
		self.sync(NotesCRM())

		doc = frappe.get_doc("Partner Lead", lead)
		doc.update({"stage": "Negotiation", "probability": "Hot"})
		doc.save(ignore_permissions=True)
		crm = NotesCRM()
		self.sync(crm)

		self.assertEqual(crm.posted("/api/resource/CRM Lead") + crm.posted("/api/resource/FCRM Note"), [])
		[note] = crm.put("/api/resource/FCRM Note/NOTE-1")
		self.assertIn("Negotiation", note["content"])
		self.assertIn("Hot", note["content"])

	def test_a_note_deleted_on_the_crm_is_written_again(self):
		lead = self.send(PARTNER)
		self.sync(NotesCRM())

		crm = NotesCRM(missing=("NOTE-1",))
		self.assertEqual(self.sync(crm)["frappe_crm_sync_status"], "Synced")
		self.assertEqual(len(crm.posted("/api/resource/FCRM Note")), 1)
		self.assertEqual(frappe.db.get_value("Partner Lead", lead, "frappe_crm_note"), "NOTE-1")

	def test_a_failed_send_is_tried_again_without_a_second_lead(self):
		self.send(PARTNER)
		broken = NotesCRM(fail_on=lambda body: body.get("reference_doctype") == "CRM Lead")
		self.assertEqual(self.sync(broken), {"frappe_crm_lead": "CRM-LEAD-NEW", "frappe_crm_sync_status": "Failed"})

		crm = NotesCRM()
		self.assertEqual(self.sync(crm)["frappe_crm_sync_status"], "Synced")
		self.assertEqual(crm.posted("/api/resource/CRM Lead"), [])
		self.assertEqual(len(crm.posted("/api/resource/FCRM Note")), 1)

	def test_only_a_system_manager_sends_a_customer_by_hand(self):
		self.send(PARTNER)
		frappe.set_user(BUYER)
		self.assertRaises(frappe.PermissionError, send_to_frappe_crm, self.customer)

		frappe.set_user("Administrator")
		with patch(f"{MODULE}.frappe_crm", return_value=SETTINGS):
			send_to_frappe_crm(self.customer)
			self.assertRaises(frappe.ValidationError, send_to_frappe_crm, "_Test No Leads Co")
		self.assertIn(self.customer, self.queued_customers())
