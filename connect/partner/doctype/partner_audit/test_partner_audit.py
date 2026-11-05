# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from connect.customer.doctype.customer_project.test_hiring import make_partner, make_partner_admin

PARTNER = "_Test Audit Partner"
ADMIN = "audit.admin@example.test"
AUDITOR = "audit.auditor@example.test"


def make_audit(**values) -> "frappe.model.document.Document":
	return frappe.get_doc(
		{"doctype": "Partner Audit", "partner": PARTNER, "proposed_audit_date": add_days(today(), 30), **values}
	).insert()


def make_auditor() -> str:
	if not frappe.db.exists("User", AUDITOR):
		frappe.get_doc({"doctype": "User", "email": AUDITOR, "first_name": "Auditor"}).insert(ignore_permissions=True)
	return AUDITOR


class IntegrationTestPartnerAudit(IntegrationTestCase):
	"""Audits Frappe runs on a partner: what a request needs, and what each status needs."""

	def setUp(self):
		make_partner(PARTNER)
		make_partner_admin(PARTNER, ADMIN)
		make_auditor()

	def test_a_request_needs_a_future_date_and_records_the_tier(self):
		with self.assertRaises(frappe.ValidationError):
			make_audit(proposed_audit_date=today())

		audit = make_audit()
		self.assertEqual(str(audit.requested_on), today())
		self.assertEqual(audit.partner_tier, frappe.db.get_value("Partner", PARTNER, "tier"))

	def test_a_scheduled_audit_needs_a_date_and_a_completed_one_its_auditor(self):
		def save_with(name, **values):
			# A fresh copy each time: a refused save leaves the old one looking edited elsewhere.
			doc = frappe.get_doc("Partner Audit", name)
			doc.update(values)
			doc.save()

		audit = make_audit().name
		self.assertRaises(frappe.ValidationError, save_with, audit, status="Scheduled")
		save_with(audit, status="Scheduled", audit_date=add_days(today(), 40))

		self.assertRaises(frappe.ValidationError, save_with, audit, status="Completed")
		save_with(audit, status="Completed", conducted_by=AUDITOR)
		self.assertEqual(frappe.db.get_value("Partner Audit", audit, "status"), "Completed")

	def test_partners_have_no_desk_access(self):
		for ptype in ("read", "create", "write"):
			self.assertFalse(frappe.has_permission("Partner Audit", ptype, user=ADMIN))
			self.assertFalse(frappe.has_permission("Partner Non Conformance", ptype, user=ADMIN))
