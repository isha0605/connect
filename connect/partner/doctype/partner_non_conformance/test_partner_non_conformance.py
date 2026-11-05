# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from connect.customer.doctype.customer_project.test_hiring import make_partner
from connect.partner.doctype.partner_audit.test_partner_audit import AUDITOR, PARTNER, make_audit, make_auditor


def raise_on(audit: str, **values) -> "frappe.model.document.Document":
	return frappe.get_doc(
		{
			"doctype": "Partner Non Conformance",
			"partner_audit": audit,
			"department": "Sales",
			"statement": "SLAs are not applied to leads.",
			**values,
		}
	).insert()


class IntegrationTestPartnerNonConformance(IntegrationTestCase):
	"""What an audit raises: on which audits, what it takes from the audit, and how it closes."""

	def setUp(self):
		make_partner(PARTNER)
		make_auditor()
		self.audit = make_audit()

	def start_audit(self):
		self.audit.update({"status": "In Progress", "audit_date": today(), "conducted_by": AUDITOR})
		self.audit.save()

	def test_raised_on_a_running_audit_and_fetches_from_it(self):
		self.assertRaises(frappe.ValidationError, raise_on, self.audit.name)

		self.start_audit()
		finding = raise_on(self.audit.name)
		self.assertEqual((finding.partner, finding.auditor, str(finding.audit_date)), (PARTNER, AUDITOR, today()))

		# moving the audit moves what its findings show
		self.audit.audit_date = add_days(today(), -1)
		self.audit.save()
		self.assertEqual(str(frappe.db.get_value("Partner Non Conformance", finding.name, "audit_date")), add_days(today(), -1))

	def test_closing_records_who_and_when_and_reopening_clears_them(self):
		self.start_audit()
		finding = raise_on(self.audit.name)
		with self.assertRaises(frappe.ValidationError):
			raise_on(self.audit.name, expected_closure=add_days(today(), -1))

		finding.status = "Closed"
		finding.save()
		self.assertEqual((str(finding.closed_on), finding.closed_by), (today(), frappe.session.user))

		finding.status = "WIP"
		finding.save()
		self.assertEqual((finding.closed_on, finding.closed_by), (None, None))
