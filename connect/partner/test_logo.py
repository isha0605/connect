# Copyright (c) 2026, Isha and Contributors
# See license.txt

from unittest.mock import patch

from frappe.tests import IntegrationTestCase

from connect.partner.logo import attach_normalized_logos


class IntegrationTestLogo(IntegrationTestCase):
	"""Client logos are built in the background; the page shows the originals meanwhile."""

	@patch("connect.partner.logo.cached_logo_url", return_value=None)
	@patch("frappe.log_error")
	@patch("frappe.enqueue", side_effect=ConnectionError("queue down"))
	def test_a_queue_failure_is_logged_once_and_the_page_still_gets_logos(self, enqueue, log_error, _cached):
		stories = [{"client_logo": "https://a.example/logo.png"}, {"client_logo": "https://b.example/logo.png"}]
		attach_normalized_logos(stories)

		self.assertEqual([row["client_logo_display"] for row in stories], [row["client_logo"] for row in stories])
		self.assertEqual(enqueue.call_count, 1)
		log_error.assert_called_once()
