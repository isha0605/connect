import frappe
from frappe.tests import IntegrationTestCase

from connect.account import get_my_context
from connect.customer.doctype.customer_project.test_hiring import make_partner, make_partner_admin

PARTNER = "_Test Managed Partner"
ADMIN = "managed.admin@example.test"
MANAGER = "partner.manager@example.test"
FORMER_MANAGER = "former.partner.manager@example.test"


def make_staff(email, first_name, enabled=1):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": first_name}).insert(ignore_permissions=True)
	frappe.db.set_value("User", email, "enabled", enabled)


class IntegrationTestPartnerManager(IntegrationTestCase):
	"""The Frappe staff a partner's team sees under Partner managers in the company menu."""

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_partner_team_sees_its_enabled_managers(self):
		make_partner(PARTNER)
		make_partner_admin(PARTNER, ADMIN)
		make_staff(MANAGER, "Aditi")
		make_staff(FORMER_MANAGER, "Karan", enabled=0)
		partner = frappe.get_doc("Partner", PARTNER)
		partner.set("partner_managers", [{"user": MANAGER}, {"user": FORMER_MANAGER}])
		partner.save(ignore_permissions=True)

		frappe.set_user(ADMIN)
		self.assertEqual(get_my_context()["partner"]["managers"], [{"full_name": "Aditi", "email": MANAGER}])
