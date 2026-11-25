# Copyright (c) 2026, Isha and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.api.partner import (
	approve_certificate_link,
	get_certificate_link_request,
	remove_certificate,
	resend_certificate_link_request,
)
from connect.customer.doctype.customer_project.test_hiring import make_partner, make_partner_admin
from connect.partner.doctype.partner.test_staff_roles import make_staff_user
from connect.partner.doctype.partner_application.partner_application import get_certificate_link_status
from connect.roles import PARTNER_MANAGER_ROLE, STAFF_ROLE

PARTNER = "_Test Cert Partner"
OTHER_PARTNER = "_Test Cert Other Partner"
ADMIN = "cert.admin@example.test"
OTHER_ADMIN = "cert.other.admin@example.test"
HOLDER = "cert.holder@example.test"
COURSE = "erpnext-distribution"
MANAGER = "cert.manager@example.test"
STAFF = "cert.staff@example.test"


class IntegrationTestCertificateLinkRequest(IntegrationTestCase):
	"""Linking a Frappe School certificate to a partner: the holder approves from an emailed link."""

	def setUp(self):
		make_partner(PARTNER)
		make_partner(OTHER_PARTNER)
		make_partner_admin(PARTNER, ADMIN)
		make_partner_admin(OTHER_PARTNER, OTHER_ADMIN)
		frappe.db.delete("Partner Certificate", {"partner_member_email": HOLDER})
		frappe.db.delete("Certificate Link Request", {"user_email": HOLDER})
		# stands in for the row _fetch_school_certificate caches from Frappe School
		self.certificate = frappe.get_doc({
			"doctype": "Partner Certificate", "course": COURSE, "school_certificate_id": "CERT-0001",
			"issue_date": "2026-03-01", "partner_member_email": HOLDER, "partner_member_name": "Cert Holder",
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def request_link(self, partner=PARTNER):
		with patch("frappe.sendmail") as sendmail:
			request = frappe.get_doc({
				"doctype": "Certificate Link Request", "partner": partner, "user_email": HOLDER, "course": COURSE,
			}).insert(ignore_permissions=True)
		# queued, so the partner doesn't wait for the mail server
		self.assertNotIn("now", sendmail.call_args.kwargs)
		return request, sendmail.call_args.kwargs["message"]

	def counts(self, partner):
		return frappe.db.get_value("Partner", partner, ["erpnext_certified", "framework_certified"])

	def test_email_links_to_the_approval_page(self):
		request, message = self.request_link()
		self.assertIn(f"/connect/certificate-approval?key={request.key}", message)
		self.assertIn("ERPNext certificate", message)

	def test_holder_approves_without_signing_in(self):
		request, _message = self.request_link()
		frappe.set_user("Guest")

		seen = get_certificate_link_request(request.key)
		self.assertEqual((seen["course"], seen["status"]), ("ERPNext", "Pending"))

		self.assertEqual(approve_certificate_link(request.key)["status"], "Approved")
		self.assertEqual(frappe.db.get_value("Partner Certificate", self.certificate.name, "partner"), PARTNER)
		# a second click on the same link changes nothing
		self.assertEqual(approve_certificate_link(request.key)["status"], "Approved")

	def test_wrong_key_is_refused(self):
		frappe.set_user("Guest")
		for key in ("", "not-a-real-key"):
			with self.subTest(key=key), self.assertRaises(frappe.DoesNotExistError):
				get_certificate_link_request(key)

	def test_holder_approval_moves_a_certificate_from_another_partner(self):
		old_request, _message = self.request_link(OTHER_PARTNER)
		with patch("frappe.sendmail"):
			approve_certificate_link(old_request.key)
		self.assertEqual(self.counts(OTHER_PARTNER), (1, 0))

		request, message = self.request_link()
		self.assertIn("confirming moves it", message)
		frappe.set_user("Guest")
		with patch("frappe.sendmail") as sendmail:
			approve_certificate_link(request.key)

		self.assertEqual(frappe.db.get_value("Partner Certificate", self.certificate.name, "partner"), PARTNER)
		self.assertEqual((self.counts(PARTNER), self.counts(OTHER_PARTNER)), ((1, 0), (0, 0)))
		self.assertEqual(frappe.db.get_value("Certificate Link Request", old_request.name, "status"), "Cancelled")
		# the old partner's admin hears that it moved
		self.assertEqual(sendmail.call_args.kwargs["recipients"], [OTHER_ADMIN])

	def test_expired_certificate_is_refused_and_does_not_count(self):
		request, _message = self.request_link()
		frappe.db.set_value("Partner Certificate", self.certificate.name, "expiry_date", "2026-01-01")
		frappe.set_user("Guest")
		with self.assertRaises(frappe.ValidationError):
			approve_certificate_link(request.key)

		# one linked before it expired still shows, but stops counting
		frappe.set_user("Administrator")
		frappe.db.set_value("Partner Certificate", self.certificate.name, "partner", PARTNER)
		frappe.set_user(ADMIN)
		status = get_certificate_link_status()
		self.assertTrue(status["linked_certificates"][0].is_expired)
		self.assertEqual(status["linked_count"], 0)

	def test_admin_removes_a_linked_certificate(self):
		request, _message = self.request_link()
		approve_certificate_link(request.key)
		self.assertEqual(self.counts(PARTNER), (1, 0))

		frappe.set_user(OTHER_ADMIN)
		with self.assertRaises(frappe.PermissionError):
			remove_certificate(self.certificate.name)

		frappe.set_user(ADMIN)
		remove_certificate(self.certificate.name)
		self.assertIsNone(frappe.db.get_value("Partner Certificate", self.certificate.name, "partner"))
		self.assertEqual(frappe.db.get_value("Certificate Link Request", request.name, "status"), "Cancelled")
		self.assertEqual(self.counts(PARTNER), (0, 0))

	def resend_as(self, user, request, resend):
		frappe.set_user(user)
		try:
			with patch("frappe.sendmail") as sendmail:
				resend(request)
		finally:
			frappe.set_user("Administrator")
		return sendmail

	def test_desk_resend_needs_write_permission(self):
		make_staff_user(STAFF, STAFF_ROLE)
		make_staff_user(MANAGER, PARTNER_MANAGER_ROLE)
		request, _message = self.request_link()
		old_key = request.key

		# Staff can read the request, which is all Frappe checks before running a document method.
		self.assertTrue(frappe.has_permission("Certificate Link Request", "read", user=STAFF))
		with self.assertRaises(frappe.PermissionError):
			self.resend_as(STAFF, request, lambda doc: frappe.get_doc(doc.doctype, doc.name).resend())
		self.assertEqual(frappe.db.get_value("Certificate Link Request", request.name, "key"), old_key)

		sendmail = self.resend_as(MANAGER, request, lambda doc: frappe.get_doc(doc.doctype, doc.name).resend())
		new_key = frappe.db.get_value("Certificate Link Request", request.name, "key")
		self.assertNotEqual(new_key, old_key)
		self.assertEqual(sendmail.call_args.kwargs["recipients"], [HOLDER])
		self.assertIn(f"key={new_key}", sendmail.call_args.kwargs["message"])

	def test_desk_resend_refuses_a_request_that_is_not_pending(self):
		request, _message = self.request_link()
		with patch("frappe.sendmail"):
			approve_certificate_link(request.key)

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Certificate Link Request", request.name).resend()

	def test_partner_resends_only_their_own_request_from_the_portal(self):
		request, _message = self.request_link()

		with self.assertRaises(frappe.PermissionError):
			self.resend_as(OTHER_ADMIN, request, lambda doc: resend_certificate_link_request(doc.name))

		sendmail = self.resend_as(ADMIN, request, lambda doc: resend_certificate_link_request(doc.name))
		self.assertNotEqual(frappe.db.get_value("Certificate Link Request", request.name, "key"), request.key)
		self.assertEqual(sendmail.call_args.kwargs["recipients"], [HOLDER])

	def test_partner_lists_linked_certificates_with_their_school_page(self):
		frappe.db.set_value("Partner Certificate", self.certificate.name, "partner", PARTNER)
		frappe.set_user(ADMIN)

		certificate = get_certificate_link_status()["linked_certificates"][0]
		self.assertEqual(certificate.course_label, "ERPNext")
		self.assertTrue(certificate.certificate_url.endswith(f"/courses/{COURSE}/CERT-0001"))
