# Copyright (c) 2026
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.brief import send_brief
from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.auth.accounts import landing_page
from connect.crm_integration import email_body
from connect.customer.doctype.project_quote.leads import get_lead, my_leads, partner_page_for_thread, update_lead
from connect.partner.doctype.partner_lead.partner_lead import NotOnCRMError

PARTNER = "_Test Leads Partner"
OTHER_PARTNER = "_Test Leads Other Partner"
OWNER = "leads.owner@example.test"
SALES = "leads.sales@example.test"
FINANCE = "leads.finance@example.test"
MEMBER = "leads.member@example.test"
OTHER_OWNER = "leads.other.owner@example.test"
BUYER = "leads.buyer@example.test"


def make_member(partner, email, access="Sales"):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": access}).insert(ignore_permissions=True)
	if not frappe.db.exists("Connect Partner Member", {"partner": partner, "user": email}):
		member = {"doctype": "Connect Partner Member", "partner": partner, "user": email, "access": access}
		frappe.get_doc(member).insert(ignore_permissions=True)


class TestLeads(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		# Each test changes the shared thread (revealing it, say); start every test afresh.
		self.addCleanup(frappe.db.rollback)
		# The new-requirement email job runs at once in tests and commits; these tests check data, not mail.
		patch("connect.notifications.frappe.enqueue").start()
		self.addCleanup(patch.stopall)
		for partner, owner in ((PARTNER, OWNER), (OTHER_PARTNER, OTHER_OWNER)):
			make_partner(partner)
			make_partner_admin(partner, owner)
		make_member(PARTNER, SALES)
		make_member(PARTNER, FINANCE, "Finance")
		make_member(PARTNER, MEMBER, "Member")
		make_buyer(BUYER, "Leads Buyer Co")
		self.customer = frappe.db.get_value("Customer Team Member", {"user": BUYER}, "customer")
		self.thread, self.quote = self.send("Batch tracking")
		self.lead = frappe.db.get_value("Project Quote", self.quote, "lead")

	def send(self, project_name):
		"""The buyer sends the partner a brief; returns the thread and its Project Quote."""
		project = frappe.get_doc(
			{"doctype": "Customer Project", "project_name": project_name, "status": "Shared", "user": BUYER}
		).insert(ignore_permissions=True)
		project.db_set("user", BUYER)
		thread = send_brief(project, self.customer, PARTNER)
		return thread, frappe.db.get_value("Project Quote", {"customer_project": project.name}, "name")

	def hire(self, quote):
		doc = frappe.get_doc("Project Quote", quote)
		doc.status = "Hired"
		doc.save(ignore_permissions=True)

	def as_user(self, user):
		frappe.set_user(user)

	def test_a_brief_is_an_open_lead_that_opens_on_its_brief(self):
		self.as_user(OWNER)
		self.assertIn(self.lead, [row["name"] for row in my_leads()["leads"]])

		lead = get_lead(self.lead)["lead"]
		self.assertEqual(lead["stage"], "Open")
		self.assertEqual(lead["company"], "Anonymous company")
		self.assertEqual(lead["messages"][0]["kind"], "brief")
		self.assertTrue(lead["needs_reply"])

	def test_sales_sees_and_works_every_team_lead(self):
		self.as_user(SALES)
		self.assertIn(self.lead, [row["name"] for row in my_leads()["leads"]])
		self.assertEqual(update_lead(self.lead, probability="Hot")["probability"], "Hot")

	def test_a_lead_without_requirements_takes_no_place_in_the_list(self):
		make_buyer("leads.empty.buyer@example.test", "Empty Leads Co")
		thread = frappe.get_doc({"doctype": "Connect Thread", "customer": "Empty Leads Co", "partner": PARTNER})
		thread.insert(ignore_permissions=True)
		thread.db_set("last_message_at", frappe.utils.add_days(frappe.utils.now_datetime(), 1))
		frappe.get_doc(
			{"doctype": "Partner Lead", "partner": PARTNER, "customer": "Empty Leads Co", "thread": thread.name}
		).insert(ignore_permissions=True)

		self.as_user(OWNER)
		with patch("connect.customer.doctype.project_quote.leads.LEAD_LIMIT", 1):
			self.assertEqual([row["name"] for row in my_leads()["leads"]], [self.lead])

	def test_another_partner_cannot_see_the_lead(self):
		self.as_user(OTHER_OWNER)
		self.assertRaises(frappe.DoesNotExistError, get_lead, self.lead)

	def test_a_customer_cannot_list_leads(self):
		self.as_user(BUYER)
		self.assertRaises(frappe.PermissionError, my_leads)

	def test_assigning_a_lead_adds_the_member_to_the_thread(self):
		self.as_user(OWNER)
		update_lead(self.lead, owner=SALES)

		self.as_user(SALES)
		self.assertEqual(get_lead(self.lead)["lead"]["owner"], SALES)
		self.assertTrue(
			frappe.db.exists("Connect Thread Member", {"thread": self.thread, "user": SALES, "is_removed": 0})
		)

	def test_a_lead_cannot_go_to_someone_off_the_team(self):
		self.as_user(OWNER)
		self.assertRaises(frappe.ValidationError, update_lead, self.lead, owner=OTHER_OWNER)

	def test_lost_needs_a_reason_and_won_comes_from_hiring(self):
		self.as_user(OWNER)
		self.assertRaises(frappe.ValidationError, update_lead, self.lead, stage="Lost")
		self.assertRaises(frappe.ValidationError, update_lead, self.lead, stage="Won")
		self.assertEqual(update_lead(self.lead, stage="Lost", lost_reason="No budget")["lost_reason"], "No budget")
		self.assertIsNone(update_lead(self.lead, stage="Negotiation")["lost_reason"])

	def test_hiring_the_partner_wins_the_lead(self):
		self.hire(self.quote)
		self.assertEqual(frappe.db.get_value("Partner Lead", self.lead, "stage"), "Won")

		self.as_user(OWNER)
		self.assertRaises(frappe.ValidationError, update_lead, self.lead, stage="Open")

	# ---- One lead per customer: every brief they send joins it ----

	def test_a_second_brief_joins_the_customers_lead(self):
		_thread, second = self.send("Payroll")
		self.assertEqual(frappe.db.get_value("Project Quote", second, "lead"), self.lead)

		self.as_user(OWNER)
		rows = [row for row in my_leads()["leads"] if row["name"] == self.lead]
		self.assertEqual(len(rows), 1)
		self.assertEqual((rows[0]["project_name"], rows[0]["requirement_count"]), ("Payroll", 2))

		lead = get_lead(self.lead)["lead"]
		self.assertEqual([r["project_name"] for r in lead["requirements"]], ["Payroll", "Batch tracking"])
		briefs = [m["title"] for m in lead["messages"] if m["kind"] == "brief"]
		self.assertEqual(briefs, ["Batch tracking", "Payroll"])

	def test_a_new_brief_reopens_a_lost_lead_with_its_owner(self):
		self.as_user(OWNER)
		update_lead(self.lead, owner=SALES)
		update_lead(self.lead, stage="Lost", lost_reason="No budget")

		self.as_user("Administrator")
		self.send("Payroll")
		lead = frappe.db.get_value("Partner Lead", self.lead, ["stage", "assigned_to", "lost_reason"], as_dict=True)
		self.assertEqual((lead.stage, lead.assigned_to, lead.lost_reason), ("Open", SALES, None))

	def test_a_won_lead_stays_won_when_a_new_brief_arrives(self):
		self.hire(self.quote)
		self.send("Payroll")
		self.assertEqual(frappe.db.get_value("Partner Lead", self.lead, "stage"), "Won")

	def test_status_is_open_until_the_partner_replies(self):
		def status():
			self.as_user(OWNER)
			row = next(row for row in my_leads()["leads"] if row["name"] == self.lead)
			self.as_user("Administrator")
			return row["communication_status"]

		def say(sender):
			message = {"doctype": "Connect Message", "thread": self.thread, "sender": sender, "content": "Hi"}
			frappe.get_doc(message).insert(ignore_permissions=True)

		self.assertEqual(status(), "Open")
		say(FINANCE)  # anyone on the partner's team replying counts
		self.assertEqual(status(), "Replied")
		say(BUYER)
		self.assertEqual(status(), "Open")

	def test_with_crm_sync_a_lead_needs_an_owner_on_the_crm(self):
		frappe.db.set_value("Connect Partner Member", {"partner": PARTNER, "user": SALES}, "crm_user", SALES)
		self.as_user(OWNER)
		with patch("connect.crm_integration.crm_settings", return_value={"name": PARTNER}):
			self.assertRaises(NotOnCRMError, update_lead, self.lead, owner=OWNER)
			self.assertEqual(update_lead(self.lead, owner=SALES)["owner"], SALES)

	def test_the_crm_owner_invited_from_the_lead_can_take_it(self):
		# The CRM named SALES as the Lead's owner; they were just invited, so not matched yet.
		frappe.db.set_value("Partner Lead", self.lead, "crm_owner", SALES)
		self.as_user(OWNER)
		with patch("connect.crm_integration.crm_settings", return_value={"name": PARTNER}):
			self.assertEqual(update_lead(self.lead, owner=SALES)["owner"], SALES)
		self.assertEqual(frappe.db.get_value("Connect Partner Member", {"partner": PARTNER, "user": SALES}, "crm_user"), SALES)

	def test_a_teammates_reply_is_the_partners_on_the_lead(self):
		message = {"doctype": "Connect Message", "thread": self.thread, "sender": MEMBER, "content": "On it"}
		frappe.get_doc(message).insert(ignore_permissions=True)
		self.as_user(OWNER)
		reply = get_lead(self.lead)["lead"]["messages"][-1]
		self.assertEqual(reply["from"], "you")
		self.assertNotEqual(reply["author"], "Anonymous company")

	def test_with_crm_sync_the_team_says_who_is_on_the_crm(self):
		frappe.db.set_value("Connect Partner Member", {"partner": PARTNER, "user": SALES}, "crm_user", SALES)
		self.as_user(OWNER)
		with patch("connect.customer.doctype.project_quote.leads.crm_settings", return_value={"name": PARTNER}):
			team = {member["user"]: member["in_crm"] for member in my_leads()["team"]}
		self.assertEqual(team, {OWNER: False, SALES: True})
		self.assertEqual({member["in_crm"] for member in my_leads()["team"]}, {None})

	# ---- Access levels: Owner and Sales work leads; Finance and Member don't see them ----

	def test_finance_and_members_cannot_open_leads(self):
		for user in (FINANCE, MEMBER):
			self.as_user(user)
			self.assertRaises(frappe.PermissionError, my_leads)
			self.assertRaises(frappe.PermissionError, get_lead, self.lead)

	def test_only_owners_and_sales_are_offered_as_lead_owners(self):
		self.as_user(OWNER)
		team = {member["user"] for member in my_leads()["team"]}
		self.assertEqual(team, {OWNER, SALES})

	def test_a_lead_cannot_go_to_finance_or_a_member(self):
		self.as_user(OWNER)
		for user in (FINANCE, MEMBER):
			self.assertRaises(frappe.ValidationError, update_lead, self.lead, owner=user)

	def test_sales_can_assign_a_lead_they_work(self):
		self.as_user(OWNER)
		update_lead(self.lead, owner=SALES)
		self.as_user(SALES)
		self.assertEqual(update_lead(self.lead, owner=OWNER)["owner"], OWNER)

	# Partners write from a lead or a customer page, so a link to a chat takes them there.
	def page_as(self, user):
		frappe.set_user(user)
		try:
			return partner_page_for_thread(self.thread)
		finally:
			frappe.set_user("Administrator")

	def test_a_chat_opens_on_its_lead(self):
		self.assertEqual(self.page_as(SALES), f"/leads/{self.lead}")

	def test_a_hired_partners_chat_opens_on_the_customer(self):
		self.hire(self.quote)
		customer = frappe.db.get_value("Partner Customer", {"partner": PARTNER, "customer": self.customer}, "name")

		self.assertEqual(self.page_as(OWNER), f"/customers/{customer}")
		# Finance sees customers but not leads.
		self.assertEqual(self.page_as(FINANCE), f"/customers/{customer}")

	def test_no_page_for_someone_who_cannot_open_it(self):
		for user in (MEMBER, FINANCE, OTHER_OWNER, BUYER):
			self.assertIsNone(self.page_as(user), user)

	def test_partners_land_on_their_home_not_messaging(self):
		self.assertEqual(landing_page(SALES), "/connect/leads")
		self.assertEqual(landing_page(FINANCE), "/connect/customers")
		self.assertEqual(landing_page(MEMBER), "/connect/partner-listing")

	# A card the partner answers on Connect links back there from their CRM.
	def crm_body(self, message_type):
		message = frappe.get_last_doc("Connect Message", {"thread": self.thread, "message_type": "Requirement"})
		return email_body(frappe._dict(message.as_dict(), message_type=message_type))

	def test_a_brief_in_the_crm_links_to_its_lead(self):
		body = self.crm_body("Requirement")
		self.assertIn(frappe.utils.get_url(f"/connect/leads/{self.lead}"), body)
		self.assertIn("Answer in Connect", body)

	def test_a_hire_request_in_the_crm_links_to_the_customer_once_hired(self):
		self.hire(self.quote)
		customer = frappe.db.get_value("Partner Customer", {"partner": PARTNER, "customer": self.customer}, "name")
		self.assertIn(frappe.utils.get_url(f"/connect/customers/{customer}"), self.crm_body("Hire Request"))

	def test_other_messages_in_the_crm_have_no_link(self):
		self.assertNotIn("Answer in Connect", self.crm_body("Quote"))
