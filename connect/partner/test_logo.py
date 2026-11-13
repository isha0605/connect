# Copyright (c) 2026, Isha and Contributors
# See license.txt

import io
import os
from unittest.mock import patch

from frappe.tests import IntegrationTestCase
from PIL import Image, ImageDraw

from connect.partner.logo import _cache_paths, _normalize, attach_normalized_logos, build_logo

RED, DARK, WHITE = (234, 50, 57, 255), (20, 20, 20, 255), (255, 255, 255, 255)


def boxed_logo(box, margin=None) -> bytes:
	"""A white bar on a coloured box, optionally inside a margin of another colour."""
	image = Image.new("RGBA", (300, 100), margin or box)
	draw = ImageDraw.Draw(image)
	if margin:
		draw.rectangle((20, 10, 279, 89), fill=box)
	draw.rectangle((100, 40, 199, 59), fill=WHITE)
	buffer = io.BytesIO()
	image.save(buffer, format="PNG")
	return buffer.getvalue()


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


class IntegrationTestLogoBoxes(IntegrationTestCase):
	"""Boxed logos keep only their artwork, made dark, so they sit on the page like the rest."""

	def assert_only_the_bar_is_left(self, raw):
		image = Image.open(io.BytesIO(_normalize(raw)))
		self.assertEqual(image.size, (100, 20))
		self.assertLess(image.convert("L").getpixel((50, 10)), 50)
		self.assertEqual(image.info["ink"], "1.000")

	def test_a_box_of_any_colour_is_removed(self):
		self.assert_only_the_bar_is_left(boxed_logo(RED))

	def test_a_box_inside_a_white_margin_is_removed(self):
		self.assert_only_the_bar_is_left(boxed_logo(DARK, margin=WHITE))

	@patch("connect.partner.logo._read_source", return_value=boxed_logo(RED))
	def test_a_built_logo_comes_with_its_shape(self, _read_source):
		source = "https://a.example/boxed-logo.png"
		path, url = _cache_paths(source)
		self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
		self.assertEqual(build_logo(source), url)

		stories = [{"client_logo": source}]
		attach_normalized_logos(stories)
		self.assertEqual(
			stories[0], {"client_logo": source, "client_logo_display": url, "client_logo_ratio": 5.0, "client_logo_ink": 1.0}
		)
