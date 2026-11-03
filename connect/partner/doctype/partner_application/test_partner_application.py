# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_partner, make_partner_admin
from connect.partner.doctype.partner_application.partner_application import unregister
from connect.partner.doctype.partner_certificate.partner_certificate import recount_certificates

PARTNER = "_Test Unregister Partner"
ADMIN = "unregister.admin@example.test"
MEMBER = "unregister.member@example.test"


class IntegrationTestPartnerApplication(IntegrationTestCase):
	"""Opting out: the partner's admin may while onboarding, never once the partnership is approved."""

	def setUp(self):
		make_partner(PARTNER)
		make_partner_admin(PARTNER, ADMIN)
		if not frappe.db.exists("User", MEMBER):
			frappe.get_doc({"doctype": "User", "email": MEMBER, "first_name": "Member"}).insert(ignore_permissions=True)
		if not frappe.db.exists("Connect Partner Member", {"partner": PARTNER, "user": MEMBER}):
			frappe.get_doc({"doctype": "Connect Partner Member", "partner": PARTNER, "user": MEMBER}).insert(
				ignore_permissions=True
			)

		frappe.db.delete("Partner Application", {"partner": PARTNER})
		frappe.db.delete("Partner Certificate", {"partner_member_email": "holder.unregister@example.test"})
		self.application = frappe.get_doc(
			{"doctype": "Partner Application", "partner": PARTNER, "company_name": PARTNER}
		).insert(ignore_permissions=True)
		self.certificate = frappe.get_doc({
			"doctype": "Partner Certificate", "course": "erpnext-training", "partner": PARTNER,
			"partner_member_email": "holder.unregister@example.test",
		}).insert(ignore_permissions=True)
		recount_certificates(PARTNER)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_admin_opts_out_while_onboarding(self):
		frappe.set_user(MEMBER)
		with self.assertRaises(frappe.PermissionError):
			unregister()

		frappe.set_user(ADMIN)
		unregister()
		self.assertFalse(frappe.db.exists("Partner Application", self.application.name))
		self.assertIsNone(frappe.db.get_value("Partner Certificate", self.certificate.name, "partner"))
		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "certs_erpnext"), 0)

	def test_approved_partnership_cannot_be_undone(self):
		self.application.db_set({"docstatus": 1, "status": "Approved"})
		frappe.set_user(ADMIN)
		with self.assertRaises(frappe.ValidationError):
			unregister()
		self.assertEqual(frappe.db.get_value("Partner Certificate", self.certificate.name, "partner"), PARTNER)
		self.assertEqual(frappe.db.get_value("Partner Application", self.application.name, "status"), "Approved")
