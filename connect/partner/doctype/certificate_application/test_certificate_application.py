# Copyright (c) 2026, Isha and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.api.partner import apply_for_certificate, cancel_certificate_application
from connect.customer.doctype.customer_project.test_hiring import make_partner, make_partner_admin
from connect.partner.doctype.certificate_application.certificate_application import (
	check_approved_applications,
	free_certification_status,
)
from connect.roles import REVIEWER_ROLE

PARTNER = "_Test Free Cert Partner"
OTHER_PARTNER = "_Test Free Cert Other Partner"
ADMIN = "freecert.admin@example.test"
OTHER_ADMIN = "freecert.other.admin@example.test"
REVIEWER = "freecert.reviewer@example.test"
MEMBER = "freecert.member@example.test"
SCHOOL = "connect.partner.doctype.certificate_link_request.certificate_link_request.school_certificates"
ISSUED = [{"name": "LMS-FREE-1", "course": "erpnext-training", "issue_date": "2026-10-01", "expiry_date": None,
	"member": MEMBER, "member_name": "Free Member"}]


class IntegrationTestCertificateApplication(IntegrationTestCase):
	"""Free certifications: for approved partners, approved by Frappe, certified from Frappe School."""

	def setUp(self):
		make_partner(PARTNER)
		make_partner(OTHER_PARTNER)
		make_partner_admin(PARTNER, ADMIN)
		make_partner_admin(OTHER_PARTNER, OTHER_ADMIN)
		if not frappe.db.exists("User", REVIEWER):
			frappe.get_doc({"doctype": "User", "email": REVIEWER, "first_name": "Reviewer"}).insert(ignore_permissions=True)
		frappe.get_doc("User", REVIEWER).add_roles(REVIEWER_ROLE)

		frappe.db.delete("Certificate Application", {"partner": ["in", [PARTNER, OTHER_PARTNER]]})
		frappe.db.delete("Certificate Link Request", {"partner": ["in", [PARTNER, OTHER_PARTNER]]})
		frappe.db.delete("Partner Certificate", {"partner_member_email": ["like", "%@example.test"], "course": "erpnext-training"})
		frappe.db.set_value("Partner", PARTNER, {"free_certifications": 2, "verification_status": "Verified"})
		self.add_paid_certificates(2)

		patch("connect.partner.doctype.certificate_application.certificate_application.is_school_enabled", return_value=True).start()
		self.sendmail = patch("frappe.sendmail").start()
		self.addCleanup(patch.stopall)

	def tearDown(self):
		frappe.set_user("Administrator")

	def add_paid_certificates(self, count):
		for index in range(count):
			frappe.get_doc({
				"doctype": "Partner Certificate", "course": "erpnext-training", "partner": PARTNER,
				"partner_member_email": f"paid{index}.freecert@example.test", "issue_date": "2025-01-01",
			}).insert(ignore_permissions=True)

	def apply(self, member=MEMBER):
		frappe.set_user(ADMIN)
		with patch(SCHOOL, return_value=[]):
			return apply_for_certificate(member, "ERPNext")["application"]

	def test_free_certifications_open_once_the_partnership_is_approved(self):
		frappe.db.set_value("Partner", PARTNER, "verification_status", "Pending Review")
		with self.assertRaises(frappe.ValidationError):
			self.apply()

		frappe.db.set_value("Partner", PARTNER, "verification_status", "Verified")
		# removing certificates later doesn't take the right away
		frappe.db.delete("Partner Certificate", {"partner": PARTNER})
		application = self.apply()
		self.assertEqual(frappe.db.get_value("Certificate Application", application, "status"), "Applied")
		self.assertEqual(free_certification_status(PARTNER)["left"], 1)
		# Frappe's reviewers hear about it
		self.assertEqual(self.sendmail.call_args.kwargs["recipients"], [REVIEWER])

	def test_reviewer_approves_and_school_certifies(self):
		application = self.apply()
		doc = frappe.get_doc("Certificate Application", application)
		with self.assertRaises(frappe.PermissionError):
			doc.approve()

		frappe.set_user(REVIEWER)
		frappe.get_doc("Certificate Application", application).approve()
		self.assertEqual(frappe.db.get_value("Certificate Application", application, "status"), "Approved")

		frappe.set_user("Administrator")
		with patch(SCHOOL, return_value=[]):
			self.assertEqual(check_approved_applications(PARTNER), [])
		with patch(SCHOOL, return_value=ISSUED):
			self.assertEqual(check_approved_applications(PARTNER), [application])

		certified = frappe.db.get_value("Certificate Application", application, ["status", "partner_certificate"], as_dict=True)
		self.assertEqual(certified.status, "Certified")
		self.assertEqual(frappe.db.get_value("Partner Certificate", certified.partner_certificate, "school_certificate_id"), "LMS-FREE-1")
		# the holder still confirms linking it, as with any certificate
		self.assertEqual(frappe.db.get_value("Certificate Link Request", {"partner": PARTNER, "user_email": MEMBER}, "status"), "Pending")

	def test_allowance_runs_out_and_a_rejection_gives_it_back(self):
		frappe.db.set_value("Partner", PARTNER, "free_certifications", 1)
		first = self.apply()
		with self.assertRaises(frappe.ValidationError):
			self.apply("second.freecert@example.test")

		frappe.set_user(REVIEWER)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Certificate Application", first).reject("")
		frappe.get_doc("Certificate Application", first).reject("Pick someone on the delivery team.")
		self.apply("second.freecert@example.test")

	def test_duplicate_or_already_certified_member_is_refused(self):
		self.apply()
		with self.assertRaises(frappe.ValidationError):
			self.apply()

		frappe.set_user(ADMIN)
		with patch(SCHOOL, return_value=ISSUED), self.assertRaises(frappe.ValidationError):
			apply_for_certificate("certified.freecert@example.test", "ERPNext")

	def test_admin_cancels_only_own_waiting_application(self):
		application = self.apply()
		frappe.set_user(OTHER_ADMIN)
		with self.assertRaises(frappe.PermissionError):
			cancel_certificate_application(application)

		frappe.set_user(ADMIN)
		cancel_certificate_application(application)
		self.assertEqual(frappe.db.get_value("Certificate Application", application, "status"), "Cancelled")
		with self.assertRaises(frappe.ValidationError):
			cancel_certificate_application(application)
		self.assertEqual(free_certification_status(PARTNER)["left"], 2)
