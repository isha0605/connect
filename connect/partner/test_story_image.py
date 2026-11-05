# Copyright (c) 2026, Isha and Contributors
# See license.txt

from unittest.mock import patch

from frappe.tests import IntegrationTestCase

from connect.partner.story_image import queue_missing_story_images


class IntegrationTestStoryImage(IntegrationTestCase):
	"""Success story cover images are fetched in the background after a partner saves."""

	@patch("frappe.log_error")
	@patch("frappe.enqueue", side_effect=ConnectionError("queue down"))
	def test_a_queue_failure_is_logged_once(self, enqueue, log_error):
		stories = [
			{"name": "row-1", "url": "https://a.example/story"},
			{"name": "row-2", "url": "https://b.example/story"},
		]
		queue_missing_story_images(stories)

		self.assertEqual(enqueue.call_count, 1)
		log_error.assert_called_once()
