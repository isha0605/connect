# Copyright (c) 2026
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.customer_project import hired_partner
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.partner.cloud_integration import (
	connect_cloud_account,
	get_cloud_account_status,
	request_cloud_link,
	retry_cloud_links,
	sync_cloud_links,
)

PARTNER = "_Test Cloud Partner"
BUYER = "cloud.buyer@example.test"
PARTNER_ADMIN = "cloud.partner.admin@example.test"
SETUP_URL = "https://cloud.example.test/dashboard/connect/customer/abc"
REGISTER = "central.api.connect.register_partner"
CREATE = "central.api.connect.create_partner_link"
READ = "central.api.connect.get_partner_link"
REGISTRATION = "central.api.connect.get_partner_registration"
REGISTER_URL = "https://cloud.example.test/dashboard/connect/partner/xyz"
STAFF = "cloud.partner.staff@example.test"


class FakeCloud:
	"""Frappe Cloud's answers by method. An exception as the answer is raised instead."""

	def __init__(self, **answers):
		self.answers = answers
		self.client = MagicMock()
		self.client.post_api.side_effect = self.answer

	def answer(self, method, params):
		result = self.answers[method]
		if isinstance(result, Exception):
			raise result
		return result

	def calls(self, method):
		return [call.args[1] for call in self.client.post_api.call_args_list if call.args[0] == method]


class TestCloudLink(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		make_partner(PARTNER)
		make_partner_admin(PARTNER, PARTNER_ADMIN)
		make_buyer(BUYER, "Cloud Buyer Co")
		frappe.db.set_value(
			"Partner", PARTNER, {"cloud_registration": "", "cloud_registration_sent_on": None}
		)
		frappe.db.set_single_value("Integration Settings", "cloud_enabled", 1)
		self.addCleanup(frappe.db.set_single_value, "Integration Settings", "cloud_enabled", 0)

		# Records stay until the class ends, so each test hires on its own project.
		self.project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": "ERP rollout", "status": "Hired", "user": BUYER}
		).insert(ignore_permissions=True)
		self.project.db_set({"user": BUYER, "partner": PARTNER, "cloud_link_status": "Pending"})
		self.email = patch("connect.partner.cloud_integration._send_registration_email").start()
		# The jobs commit per project; a test's records must still roll back.
		patch("connect.partner.cloud_integration.frappe.db.commit").start()
		self.addCleanup(patch.stopall)

	def run_with(self, cloud: FakeCloud):
		with patch("connect.partner.cloud_integration._get_cloud_client", return_value=cloud.client):
			request_cloud_link(self.project.name)
		self.project.reload()

	def test_a_registered_partner_gets_the_customers_setup_link(self):
		frappe.db.set_value("Partner", PARTNER, "cloud_registration", "Completed")
		cloud = FakeCloud(**{CREATE: {"status": "Requested", "url": SETUP_URL}})
		self.run_with(cloud)

		(sent,) = cloud.calls(CREATE)
		self.assertEqual((sent["connect_partner_id"], sent["engagement_id"]), (PARTNER, self.project.name))
		self.assertEqual(sent["customer_email"], BUYER)
		self.assertIn(f"/connect/custom-implementation?project={self.project.name}", sent["return_url"])
		self.assertEqual(cloud.calls(REGISTER), [])
		self.assertEqual(
			(self.project.cloud_link_status, self.project.cloud_setup_url), ("Requested", SETUP_URL)
		)
		self.assertEqual(hired_partner(self.project)["central_setup_url"], SETUP_URL)

	def test_an_unregistered_partner_is_asked_once_and_the_hire_waits(self):
		cloud = FakeCloud(
			**{
				REGISTER: {
					"status": "Pending",
					"url": "https://cloud.example.test/dashboard/connect/partner/k3",
				},
				CREATE: frappe.ValidationError("Partner is not registered on Frappe Cloud."),
			}
		)
		self.run_with(cloud)
		self.run_with(cloud)

		self.assertEqual(len(cloud.calls(REGISTER)), 1)
		self.assertEqual(cloud.calls(REGISTER)[0]["owner_email"], PARTNER_ADMIN)
		self.email.assert_called_once()
		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "cloud_registration"), "Pending")
		self.assertEqual(self.project.cloud_link_status, "Waiting for Partner")
		self.assertIsNone(hired_partner(self.project)["central_setup_url"])

	def test_once_the_partner_registers_the_retry_links_the_hire(self):
		frappe.db.set_value(
			"Partner",
			PARTNER,
			{"cloud_registration": "Pending", "cloud_registration_sent_on": frappe.utils.now()},
		)
		self.project.db_set("cloud_link_status", "Waiting for Partner")
		cloud = FakeCloud(**{CREATE: {"status": "Requested", "url": SETUP_URL}})
		with patch("connect.partner.cloud_integration._get_cloud_client", return_value=cloud.client):
			retry_cloud_links()
		self.project.reload()

		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "cloud_registration"), "Completed")
		self.assertEqual(self.project.cloud_link_status, "Requested")

	def test_frappe_cloud_being_down_keeps_the_hire_pending_with_the_error(self):
		frappe.db.set_value("Partner", PARTNER, "cloud_registration", "Completed")
		self.run_with(FakeCloud(**{CREATE: ConnectionError("Frappe Cloud is down")}))

		self.assertEqual(self.project.cloud_link_status, "Pending")
		self.assertIn("Frappe Cloud is down", self.project.cloud_link_error)

	def test_the_setup_link_goes_once_the_customer_has_answered(self):
		self.project.db_set({"cloud_link_status": "Active", "cloud_setup_url": SETUP_URL})
		self.assertIsNone(hired_partner(self.project)["central_setup_url"])

	def sync_with(self, cloud: FakeCloud):
		with patch("connect.partner.cloud_integration._get_cloud_client", return_value=cloud.client):
			sync_cloud_links()
		self.project.reload()

	def test_the_customers_answer_comes_back_and_the_setup_link_goes(self):
		self.project.db_set({"cloud_link_status": "Requested", "cloud_setup_url": SETUP_URL})
		cloud = FakeCloud(**{READ: {"status": "Active", "customer_team": "TEAM-00012"}})
		self.sync_with(cloud)

		self.assertIn({"engagement_id": self.project.name}, cloud.calls(READ))
		self.assertEqual((self.project.cloud_link_status, self.project.cloud_setup_url), ("Active", None))

	def test_a_failed_read_keeps_what_connect_knew(self):
		self.project.db_set({"cloud_link_status": "Requested", "cloud_setup_url": SETUP_URL})
		self.sync_with(FakeCloud(**{READ: ConnectionError("Frappe Cloud is down")}))
		self.assertEqual(
			(self.project.cloud_link_status, self.project.cloud_setup_url), ("Requested", SETUP_URL)
		)


class TestCloudAccountStep(IntegrationTestCase):
	"""Partner onboarding's "Connect your Frappe Cloud account" step, and the approval it gates."""

	def setUp(self):
		frappe.set_user("Administrator")
		make_partner(PARTNER)
		make_partner_admin(PARTNER, PARTNER_ADMIN)
		frappe.db.set_value(
			"Partner", PARTNER, {"cloud_registration": "", "cloud_registration_sent_on": None}
		)
		frappe.db.set_single_value("Integration Settings", "cloud_enabled", 1)
		self.addCleanup(frappe.db.set_single_value, "Integration Settings", "cloud_enabled", 0)
		self.addCleanup(frappe.set_user, "Administrator")

	def as_user(self, user, cloud: FakeCloud, action):
		frappe.set_user(user)
		with patch("connect.partner.cloud_integration._get_cloud_client", return_value=cloud.client):
			return action()

	def test_the_admin_gets_a_link_that_comes_back_to_onboarding(self):
		cloud = FakeCloud(**{REGISTER: {"status": "Pending", "url": REGISTER_URL}})
		result = self.as_user(PARTNER_ADMIN, cloud, connect_cloud_account)

		(sent,) = cloud.calls(REGISTER)
		self.assertEqual(
			(sent["owner_email"], result), (PARTNER_ADMIN, {"completed": False, "url": REGISTER_URL})
		)
		self.assertTrue(sent["return_url"].endswith("/connect/partner-onboarding"))
		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "cloud_registration"), "Pending")

	def test_only_the_admin_can_connect_frappe_cloud(self):
		if not frappe.db.exists("User", STAFF):
			frappe.get_doc({"doctype": "User", "email": STAFF, "first_name": "Staff"}).insert(
				ignore_permissions=True
			)
		if not frappe.db.exists("Connect Partner Member", {"partner": PARTNER, "user": STAFF}):
			frappe.get_doc(
				{"doctype": "Connect Partner Member", "partner": PARTNER, "user": STAFF, "is_admin": 0}
			).insert(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			self.as_user(STAFF, FakeCloud(), connect_cloud_account)

	def test_the_step_is_done_once_frappe_cloud_has_the_team(self):
		waiting = FakeCloud(**{REGISTRATION: {"status": "Pending", "team": None}})
		self.assertEqual(
			self.as_user(PARTNER_ADMIN, waiting, get_cloud_account_status),
			{"enabled": True, "completed": False},
		)

		done = FakeCloud(**{REGISTRATION: {"status": "Completed", "team": "TEAM-00002"}})
		self.assertEqual(
			self.as_user(PARTNER_ADMIN, done, get_cloud_account_status), {"enabled": True, "completed": True}
		)
		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "cloud_registration"), "Completed")

	def test_an_application_needs_the_frappe_cloud_account_to_be_submitted(self):
		application = frappe.new_doc("Partner Application")
		application.partner = PARTNER
		with self.assertRaises(frappe.ValidationError):
			application._validate_cloud_account()

		frappe.db.set_value("Partner", PARTNER, "cloud_registration", "Completed")
		application._validate_cloud_account()
