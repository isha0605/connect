# Copyright (c) 2026, Isha and Contributors
# See license.txt

from unittest.mock import patch

from frappe.tests import IntegrationTestCase

from connect.partner.story_apps import apps_from_stories, apps_in_story_page, queue_missing_story_apps

KNOWN_APPS = ["ERPNext", "Frappe HR", "Helpdesk", "Frappe Insights"]

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
