# Copyright (c) 2026, Isha and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.permissions import reset_perms
from frappe.tests import IntegrationTestCase

from connect.api.partner import apply_for_certificate, cancel_certificate_application
from connect.customer.doctype.customer_project.test_hiring import make_partner, make_partner_admin
from connect.partner.doctype.certificate_application.certificate_application import (
	check_approved_applications,
	free_certification_status,
	reviewer_emails,
)
from connect.roles import PARTNER_MANAGER_ROLE

PARTNER = "_Test Free Cert Partner"
OTHER_PARTNER = "_Test Free Cert Other Partner"
ADMIN = "freecert.admin@example.test"
OTHER_ADMIN = "freecert.other.admin@example.test"
REVIEWER = "freecert.reviewer@example.test"
MEMBER = "freecert.member@example.test"
SCHOOL = "connect.partner.doctype.certificate_link_request.certificate_link_request.school_certificates"
ISSUED = [{"name": "LMS-FREE-1", "course": "erpnext-training", "issue_date": "2026-10-01", "expiry_date": None,
	"member": MEMBER, "member_name": "Free Member"}]


def make_staff_user(email, role, rights, doctype="Certificate Application"):
	"""A Desk user whose only role is a new staff role holding `rights` on `doctype`, set up as a
	System Manager would in Role Permissions Manager. The caller resets the doctype's permissions."""
	from frappe.permissions import add_permission, update_permission_property

	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)
	add_permission(doctype, role)
	for right in rights:
		update_permission_property(doctype, role, 0, right, 1)

	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Staff", "user_type": "System User"}).insert(
			ignore_permissions=True
		)
	frappe.get_doc("User", email).add_roles(role)
	return email


class IntegrationTestCertificateApplication(IntegrationTestCase):
	"""Free certifications: for approved partners, approved by Frappe, certified from Frappe School."""

	def setUp(self):
		make_partner(PARTNER)
		make_partner(OTHER_PARTNER)
		make_partner_admin(PARTNER, ADMIN)
		make_partner_admin(OTHER_PARTNER, OTHER_ADMIN)
		if not frappe.db.exists("User", REVIEWER):
			frappe.get_doc({"doctype": "User", "email": REVIEWER, "first_name": "Reviewer"}).insert(ignore_permissions=True)
		frappe.get_doc("User", REVIEWER).add_roles(PARTNER_MANAGER_ROLE)

		frappe.db.delete("Certificate Application", {"partner": ["in", [PARTNER, OTHER_PARTNER]]})
		frappe.db.delete("Certificate Link Request", {"partner": ["in", [PARTNER, OTHER_PARTNER]]})
		frappe.db.delete("Partner Certificate", {"partner_member_email": ["like", "%@example.test"], "course": "erpnext-training"})
		frappe.db.set_value("Partner", PARTNER, {"free_certifications": 2, "verification_status": "Verified"})
		self.add_paid_certificates(2)

		patch("connect.partner.doctype.certificate_application.certificate_application.is_school_enabled", return_value=True).start()
		self.sendmail = patch("frappe.sendmail").start()
		self.addCleanup(patch.stopall)
		# Staff roles a test grants in Role Permissions Manager are Custom DocPerm rows.
		self.addCleanup(frappe.clear_cache, doctype="Certificate Application")
		self.addCleanup(reset_perms, "Certificate Application")

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

	def test_a_staff_role_given_review_in_desk_approves(self):
		"""A System Manager makes a new staff role and ticks Review in Role Permissions Manager."""
		senior = make_staff_user("senior.freecert@example.test", "_Test Senior Reviewer", ("read", "write", "review"))
		application = self.apply()

		frappe.set_user(senior)
		frappe.get_doc("Certificate Application", application).approve()

		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Certificate Application", application, "status"), "Approved")
		self.assertIn(senior, reviewer_emails())

	def test_a_staff_role_without_review_cannot_approve(self):
		clerk = make_staff_user("clerk.freecert@example.test", "_Test Review Clerk", ("read", "write"))
		application = self.apply()

		frappe.set_user(clerk)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Certificate Application", application).approve()

	def test_a_site_with_saved_permissions_keeps_review_for_reviewers(self):
		"""A site that customised these permissions before Review existed gets it from the patch."""
		from frappe.permissions import setup_custom_perms

		from connect.patches.grant_review_on_custom_permissions import execute

		setup_custom_perms("Certificate Application")
		saved = {"parent": "Certificate Application", "role": PARTNER_MANAGER_ROLE, "permlevel": 0}
		frappe.db.set_value("Custom DocPerm", saved, "review", 0)
		frappe.clear_cache(doctype="Certificate Application")
		self.assertNotIn(REVIEWER, reviewer_emails())

		execute()
		self.assertEqual(frappe.db.get_value("Custom DocPerm", saved, "review"), 1)
		self.assertIn(REVIEWER, reviewer_emails())

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

	def test_status_only_moves_forward_even_through_a_direct_save(self):
		def save_with(name, **values):
			doc = frappe.get_doc("Certificate Application", name)
			doc.update(values)
			doc.save(ignore_permissions=True)

		application = self.apply()
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			save_with(application, status="Certified")

		save_with(application, status="Approved")
		with self.assertRaises(frappe.ValidationError):
			save_with(application, status="Certified")
		with self.assertRaises(frappe.ValidationError):
			save_with(application, status="Applied")

		other = self.apply("other.freecert@example.test")
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			save_with(other, status="Rejected")
		save_with(other, status="Rejected", rejection_reason="Pick someone on the delivery team.")
		with self.assertRaises(frappe.ValidationError):
			save_with(other, status="Applied")

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
