# Copyright (c) 2026
# See license.txt

import io
from unittest.mock import patch

import frappe
import requests
from frappe.tests import IntegrationTestCase
from PIL import Image
from pypdf import PdfWriter

from connect.partner.migration.files import copy_files
from connect.partner.migration.run import migrate
from connect.partner.migration.test_run import (
	NEW_OWNER,
	PARTNER_ID,
	frappe_io_partner,
	make_exports,
	make_records,
)

FRAPPE_IO = "https://frappe-io.example.test"
PRESS = "https://press.example.test"
KEY = {"Authorization": "token key:secret"}


def make_pdf() -> bytes:
	"""A real, blank PDF: Frappe reads every PDF it saves, to check it for scripts."""
	writer = PdfWriter()
	writer.add_blank_page(width=72, height=72)
	content = io.BytesIO()
	writer.write(content)
	return content.getvalue()


def make_jpeg() -> bytes:
	"""A real JPEG: Frappe opens JPEGs to strip their EXIF data."""
	content = io.BytesIO()
	Image.new("RGB", (10, 10)).save(content, format="JPEG")
	return content.getvalue()


class FakeResponse:
	def __init__(
		self, content: bytes = b"", status: int = 200, content_type: str = "application/octet-stream"
	):
		self.content, self.status = content, status
		self.headers = {"Content-Type": content_type}

	def raise_for_status(self):
		if self.status >= 400:
			raise requests.HTTPError(f"{self.status} Error")


class FakeSite:
	"""A source site's client that serves files from memory and notes every download."""

	def __init__(self, url: str, files: dict[str, bytes]):
		self.url, self.headers, self.verify = url, KEY, True
		self.files, self.downloads, self.pages = files, [], set()
		self.session = self

	def get(self, url, headers=None, verify=True, timeout=None):
		self.downloads.append((url, headers))
		if url in self.pages:
			return FakeResponse(b"<html>Sign in</html>", content_type="text/html; charset=utf-8")
		return FakeResponse(self.files[url]) if url in self.files else FakeResponse(status=404)


class TestCopyFiles(IntegrationTestCase):
	def setUp(self):
		self.frappe_io = FakeSite(FRAPPE_IO, {f"{FRAPPE_IO}/files/migrated.png": b"frappe.io logo"})
		self.press = FakeSite(
			PRESS,
			{
				f"{PRESS}/private/files/incorporation.pdf": make_pdf(),
				f"{PRESS}/private/files/audit.pdf": make_pdf(),
			},
		)

	def tearDown(self):
		frappe.db.rollback()

	def copy(self):
		# Each copied file is committed at once in the job; here it stays in the test's transaction.
		with patch.object(frappe.db, "commit"):
			return copy_files({"frappe.io": self.frappe_io, "Press": self.press})

	def test_each_noted_file_reaches_its_record_and_only_logos_are_public(self):
		migrate(make_records())

		report = self.copy()

		# Both partners' logos, the applicant's certificate, and the audit report.
		self.assertEqual(len(report.lines["files_copied"]), 4, dict(report.lines))
		self.assertTrue(frappe.db.get_value("Partner", PARTNER_ID, "logo").startswith("/files/"))
		application = frappe.db.get_value(
			"Partner Application", {"company_email": NEW_OWNER}, "incorporation_certificate"
		)
		self.assertTrue(application.startswith("/private/files/"))
		audit_report = frappe.db.get_value("Partner Audit", {"partner": PARTNER_ID}, "audit_report")
		self.assertTrue(audit_report.startswith("/private/files/"))

	def test_a_file_already_in_connect_is_left_as_it_is(self):
		migrate(make_records())
		frappe.db.set_value("Partner", PARTNER_ID, "logo", "/files/uploaded-in-connect.png")

		report = self.copy()

		self.assertEqual(frappe.db.get_value("Partner", PARTNER_ID, "logo"), "/files/uploaded-in-connect.png")
		self.assertIn(f"Partner {PARTNER_ID}: logo", report.lines["files_already_there"])
		# Only the other frappe.io partner's logo is fetched.
		self.assertEqual(self.frappe_io.downloads, [(f"{FRAPPE_IO}/files/migrated.png", KEY)])

	def test_a_file_that_cant_be_fetched_is_listed_and_the_rest_carry_on(self):
		migrate(make_records())
		del self.press.files[f"{PRESS}/private/files/incorporation.pdf"]

		report = self.copy()

		(failure,) = report.lines["files_failed"]
		self.assertTrue("incorporation_certificate" in failure and "404" in failure)
		self.assertEqual(len(report.lines["files_copied"]), 3)
		self.assertTrue(report.has_problems())

	def test_the_key_goes_only_to_the_source_site(self):
		elsewhere = "https://cdn.example.test/acme.png"
		exports = make_exports()
		exports[("frappe.io", "Partner")][0] = frappe_io_partner(logo=elsewhere)
		migrate(make_records(exports))
		self.frappe_io.files[elsewhere] = b"logo on a cdn"

		self.copy()

		self.assertIn((elsewhere, None), self.frappe_io.downloads)
		sites = self.frappe_io.downloads + self.press.downloads
		self.assertTrue(all(url.startswith((FRAPPE_IO, PRESS)) for url, headers in sites if headers == KEY))

	def test_a_pdf_that_cant_be_read_is_listed_and_the_rest_carry_on(self):
		migrate(make_records())
		self.press.files[f"{PRESS}/private/files/audit.pdf"] = b"not a pdf"

		report = self.copy()

		(failure,) = report.lines["files_failed"]
		self.assertIn("audit_report", failure)
		self.assertEqual(len(report.lines["files_copied"]), 3)

	def test_an_image_too_big_to_open_is_listed_and_the_rest_carry_on(self):
		logo = f"{FRAPPE_IO}/files/huge.jpg"
		exports = make_exports()
		exports[("frappe.io", "Partner")][0] = frappe_io_partner(logo=logo)
		migrate(make_records(exports))
		self.frappe_io.files[logo] = make_jpeg()
		frappe.db.set_single_value("System Settings", "strip_exif_metadata_from_uploaded_images", 1)

		# Pillow refuses an image over twice this many pixels as a decompression bomb.
		with patch.object(Image, "MAX_IMAGE_PIXELS", 10):
			report = self.copy()

		(failure,) = report.lines["files_failed"]
		self.assertTrue("logo" in failure and "decompression bomb" in failure)
		self.assertEqual(len(report.lines["files_copied"]), 3)

	def test_only_the_given_sources_files_are_copied(self):
		migrate(make_records())

		with patch.object(frappe.db, "commit"):
			report = copy_files({"frappe.io": self.frappe_io})

		self.assertEqual(len(report.lines["files_copied"]), 2)
		self.assertEqual(self.press.downloads, [])

	def test_a_sign_in_page_isnt_saved_as_the_file(self):
		migrate(make_records())
		self.press.pages.add(f"{PRESS}/private/files/audit.pdf")

		report = self.copy()

		(failure,) = report.lines["files_failed"]
		self.assertIn("web page", failure)
		self.assertFalse(frappe.db.get_value("Partner Audit", {"partner": PARTNER_ID}, "audit_report"))

	def test_a_second_run_copies_nothing_new(self):
		migrate(make_records())
		self.copy()

		report = self.copy()

		self.assertNotIn("files_copied", report.lines)
		self.assertEqual(len(report.lines["files_already_there"]), 4)
