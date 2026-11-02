# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.partner.doctype.partner.partner import get_my_profile, update_my_partner_profile

PARTNER = "_Test Profile Partner"
OTHER_PARTNER = "_Test Profile Other Partner"
ADMIN = "profile.admin@example.test"
MEMBER = "profile.member@example.test"
OTHER_ADMIN = "profile.other.admin@example.test"
BUYER = "profile.buyer@example.test"


class IntegrationTestMyProfile(IntegrationTestCase):
	"""A partner's Profile builder: its own public profile, which only its admin may change."""

	def setUp(self):
		make_partner(PARTNER)
		make_partner(OTHER_PARTNER)
		make_partner_admin(PARTNER, ADMIN)
		make_partner_admin(OTHER_PARTNER, OTHER_ADMIN)
		if not frappe.db.exists("User", MEMBER):
			frappe.get_doc({"doctype": "User", "email": MEMBER, "first_name": "Member"}).insert(
				ignore_permissions=True
			)
		if not frappe.db.exists("Connect Partner Member", {"partner": PARTNER, "user": MEMBER}):
			frappe.get_doc({"doctype": "Connect Partner Member", "partner": PARTNER, "user": MEMBER}).insert(
				ignore_permissions=True
			)
		make_buyer(BUYER, "_Test Profile Buyer Co")

		partner = frappe.get_doc("Partner", PARTNER)
		partner.website = "https://profile.example.test"
		partner.set("success_stories", [])
		for client in ("Refex", "Motovolt"):
			partner.append(
				"success_stories",
				{"client_name": client, "headline": f"{client} story", "cover_image": f"/files/{client}.png"},
			)
		partner.save(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_admin_reads_own_profile_and_can_edit(self):
		frappe.set_user(ADMIN)
		profile = get_my_profile()

		self.assertEqual(profile["partner"], PARTNER)
		self.assertEqual(profile["website"], "https://profile.example.test")
		self.assertEqual([story["client_name"] for story in profile["success_stories"]], ["Refex", "Motovolt"])
		self.assertTrue(profile["can_edit"])

	def test_member_reads_but_cannot_edit(self):
		frappe.set_user(MEMBER)
		self.assertFalse(get_my_profile()["can_edit"])

		with self.assertRaises(frappe.PermissionError):
			update_my_partner_profile(website="https://changed.example.test")
		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "website"), "https://profile.example.test")

	def test_admin_saves_new_fields(self):
		frappe.set_user(ADMIN)
		update_my_partner_profile(
			phone="+91 98408 35346", team_size="11-50", journey_blog_url="https://blog.example.test/journey"
		)

		saved = frappe.db.get_value("Partner", PARTNER, ["phone", "team_size", "journey_blog_url"], as_dict=True)
		self.assertEqual(saved.phone, "+91 98408 35346")
		self.assertEqual(saved.team_size, "11-50")
		self.assertEqual(saved.journey_blog_url, "https://blog.example.test/journey")

	def test_admin_edits_only_own_partner(self):
		frappe.set_user(OTHER_ADMIN)
		update_my_partner_profile(website="https://other.example.test")

		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "website"), "https://profile.example.test")
		self.assertEqual(frappe.db.get_value("Partner", OTHER_PARTNER, "website"), "https://other.example.test")

	def test_customer_is_refused(self):
		frappe.set_user(BUYER)
		with self.assertRaises(frappe.PermissionError):
			get_my_profile()

	def test_admin_saves_gallery_and_keeps_story_covers(self):
		frappe.set_user(ADMIN)
		stories = get_my_profile()["success_stories"]
		update_my_partner_profile(
			photos=[{"image": "/files/team.png"}, {"image": "/files/office.png", "video": "/files/tour.mp4"}],
			success_stories=stories,
			why_choose_them="We ship.",
			how_we_work="Weekly demos.",
			successful_implementation="Live in six weeks.",
		)

		profile = get_my_profile()
		self.assertEqual([photo["image"] for photo in profile["photos"]], ["/files/team.png", "/files/office.png"])
		self.assertEqual(profile["success_stories"][0]["cover_image"], "/files/Refex.png")
		self.assertEqual(profile["why_choose_them"], "We ship.")
		self.assertEqual(profile["how_we_work"], "Weekly demos.")
		self.assertEqual(profile["successful_implementation"], "Live in six weeks.")

	def test_rejects_text_over_its_limit(self):
		frappe.set_user(ADMIN)
		with self.assertRaises(frappe.ValidationError):
			update_my_partner_profile(tagline="x" * 81)
		with self.assertRaises(frappe.ValidationError):
			update_my_partner_profile(founder={"member_name": "Asha", "bio": "x" * 281})

		update_my_partner_profile(tagline="x" * 80)
		self.assertEqual(len(frappe.db.get_value("Partner", PARTNER, "tagline")), 80)

	def test_rejects_links_that_are_not_uploads_or_https(self):
		frappe.set_user(ADMIN)
		for link in ("javascript:alert(1)", "http://tracker.example.test/pixel.png"):
			with self.subTest(link=link), self.assertRaises(frappe.ValidationError):
				update_my_partner_profile(logo=link)
		self.assertFalse(frappe.db.get_value("Partner", PARTNER, "logo"))

	def test_admin_sets_hourly_rate_and_reads_verification(self):
		frappe.db.set_value("Partner", PARTNER, "verification_status", "Verified")
		frappe.set_user(ADMIN)
		update_my_partner_profile(hourly_rate=2500)

		profile = get_my_profile()
		self.assertEqual(profile["hourly_rate"], 2500)
		self.assertTrue(profile["is_verified"])

		with self.assertRaises(frappe.ValidationError):
			update_my_partner_profile(hourly_rate=-1)
		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "hourly_rate"), 2500)

	def test_industries_follow_the_public_profile(self):
		frappe.set_user(ADMIN)
		stories = [
			{"client_name": "Refex", "headline": "Refex story", "category": "Agriculture"},
			{"client_name": "Motovolt", "headline": "Motovolt story", "category": "Agriculture"},
			{"client_name": "Kestrel", "headline": "Kestrel story", "category": "Logistics"},
		]
		update_my_partner_profile(industry="Manufacturing", success_stories=stories)

		# a story industry counts once it has two stories, as on the public profile
		self.assertEqual(get_my_profile()["display_industries"], ["Manufacturing", "Agriculture"])
