# Copyright (c) 2026, Isha and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_partner
from connect.partner.story_apps import (
	apps_from_stories,
	apps_in_story_page,
	build_story_apps,
	queue_missing_story_apps,
)
from connect.patches.add_lending_and_education_apps import execute as add_lending_and_education_apps

KNOWN_APPS = ["ERPNext", "Frappe HR", "Helpdesk", "Frappe Insights"]
PARTNER = "_Test Story Apps Partner"


def make_apps():
	for app in KNOWN_APPS:
		if not frappe.db.exists("App", app):
			frappe.get_doc({"doctype": "App", "title": app}).insert(ignore_permissions=True)


def partner_with_stories(*story_apps):
	"""The test partner with one success story per entry in `story_apps`, each a list of apps."""
	make_apps()
	make_partner(PARTNER)
	doc = frappe.get_doc("Partner", PARTNER)
	doc.set("success_stories", [{"client_name": f"Client {index}", "apps": "\n".join(apps)} for index, apps in enumerate(story_apps)])
	doc.save(ignore_permissions=True)
	return doc


def partner_apps():
	return frappe.get_all("Partner App", filters={"parent": PARTNER, "parenttype": "Partner"}, pluck="app", order_by="idx")

# The shape of a frappe.io story page: the heading, one block per app, then the next heading.
STORY_PAGE = """
<div><p>Apps implemented</p></div>
<div>
	<div><img src="/files/erpnext.png"/><div class="__text_block__">ERPNext</div></div>
	<div><img src="/files/erpnext.png"/><div class="__text_block__">ERPNext</div></div>
	<div><img src="/files/hr.png"/><div class="__text_block__">Frappe HR</div></div>
	<div><img src="/files/helpdesk.png"/><div class="__text_block__">Frappe Helpdesk</div></div>
	<div><img src="/files/other.png"/><div class="__text_block__">Some Other App</div></div>
</div>
<div><p>Industry</p></div>
<div><div class="__text_block__">Insights</div></div>
"""


class IntegrationTestStoryApps(IntegrationTestCase):
	"""Success stories keep the apps their frappe.io page lists, for the profile to show."""

	def test_reads_known_apps_once_and_stops_at_the_next_heading(self):
		self.assertEqual(apps_in_story_page(STORY_PAGE, KNOWN_APPS), ["ERPNext", "Frappe HR", "Helpdesk"])

	def test_lending_and_education_are_apps_with_their_logos(self):
		add_lending_and_education_apps()

		for app, icon in (("Frappe Lending", "lending.png"), ("Frappe Education", "education.png")):
			self.assertEqual(frappe.db.get_value("App", app, "logo"), f"/assets/connect/images/app_icons/{icon}")
		page = STORY_PAGE.replace("Some Other App", "Lending").replace("Frappe HR", "Education")
		self.assertEqual(
			apps_in_story_page(page, [*KNOWN_APPS, "Frappe Lending", "Frappe Education"]),
			["ERPNext", "Frappe Education", "Helpdesk", "Frappe Lending"],
		)

	def test_the_learning_app_gets_its_logo(self):
		if not frappe.db.exists("App", "Learning"):
			frappe.get_doc({"doctype": "App", "title": "Learning"}).insert()
		frappe.db.set_value("App", "Learning", "logo", None)

		add_lending_and_education_apps()

		self.assertEqual(frappe.db.get_value("App", "Learning", "logo"), "/assets/connect/images/app_icons/learning.png")

	def test_a_page_without_the_list_has_no_apps(self):
		self.assertEqual(apps_in_story_page("<p>Industry</p><div>ERPNext</div>", KNOWN_APPS), [])

	def test_apps_from_stories_lists_each_app_once(self):
		stories = [{"apps": "ERPNext\nFrappe HR"}, {"apps": None}, {"apps": "Frappe HR\nHelpdesk"}]
		self.assertEqual(apps_from_stories(stories), ["ERPNext", "Frappe HR", "Helpdesk"])

	@patch("frappe.enqueue")
	def test_queues_only_frappe_io_stories_without_apps(self, enqueue):
		stories = [
			{"name": "row-1", "url": "https://frappe.io/stories/Meena%20Gas"},
			{"name": "row-2", "url": "https://frappe.io/stories/Done", "apps": "ERPNext"},
			{"name": "row-3", "url": "https://partner.example/case-study"},
		]
		queue_missing_story_apps(stories)

		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["row_name"], "row-1")


class IntegrationTestPartnerAppsFromStories(IntegrationTestCase):
	"""A partner's apps are only the apps its success stories name."""

	def test_saving_a_partner_sets_its_apps_from_its_stories(self):
		partner_with_stories(["ERPNext", "Frappe HR"], ["Frappe HR", "Helpdesk"])
		self.assertEqual(partner_apps(), ["ERPNext", "Frappe HR", "Helpdesk"])

	def test_an_app_no_story_names_is_dropped(self):
		doc = partner_with_stories(["ERPNext"])
		doc.append("apps", {"app": "Frappe Insights"})
		doc.save(ignore_permissions=True)

		self.assertEqual(partner_apps(), ["ERPNext"])

	def test_removing_a_story_removes_its_apps(self):
		doc = partner_with_stories(["ERPNext"], ["Helpdesk"])
		doc.success_stories.pop()
		doc.save(ignore_permissions=True)

		self.assertEqual(partner_apps(), ["ERPNext"])

	def test_a_fetched_story_page_updates_the_partner_apps(self):
		doc = partner_with_stories([])
		row = doc.success_stories[0].name

		with patch("connect.partner.story_apps.fetch_story_page", return_value=STORY_PAGE):
			build_story_apps(row, "https://frappe.io/stories/Client%200")

		self.assertEqual(partner_apps(), ["ERPNext", "Frappe HR", "Helpdesk"])
