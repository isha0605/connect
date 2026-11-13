# Copyright (c) 2026, Isha and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from connect.customer.doctype.customer_project.test_hiring import make_buyer, make_partner, make_partner_admin
from connect.partner.doctype.partner.partner import (
	discard_my_profile_draft,
	get_my_profile,
	publish_my_profile_draft,
	update_my_partner_profile,
)

PARTNER = "_Test Profile Partner"
OTHER_PARTNER = "_Test Profile Other Partner"
ADMIN = "profile.admin@example.test"
MEMBER = "profile.member@example.test"
OTHER_ADMIN = "profile.other.admin@example.test"
BUYER = "profile.buyer@example.test"
INDUSTRY_NAMES = ["Textile Manufacturing", "Retail", "Agriculture", "Education", "Finance", "Logistics", "Hospitality"]


def make_industries():
	for name in ["Manufacturing", *INDUSTRY_NAMES]:
		if not frappe.db.exists("Industry", name):
			group = "Manufacturing" if name.endswith("Manufacturing") and name != "Manufacturing" else None
			frappe.get_doc({"doctype": "Industry", "title": name, "industry_group": group}).insert(ignore_permissions=True)


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
		partner.tagline = "The live tagline"
		partner.profile_draft = None
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

	def test_admin_picks_how_they_work(self):
		for mode in ("Remote", "Onsite"):
			if not frappe.db.exists("Delivery Mode", mode):
				frappe.get_doc({"doctype": "Delivery Mode", "title": mode}).insert(ignore_permissions=True)
		frappe.set_user(ADMIN)
		update_my_partner_profile(delivery_options=["Remote", "Onsite"])

		profile = get_my_profile()
		self.assertEqual(profile["delivery_options"], ["Remote", "Onsite"])
		self.assertIn("Onsite", profile["options"]["delivery_modes"])

	def test_admin_edits_only_own_partner(self):
		frappe.set_user(OTHER_ADMIN)
		update_my_partner_profile(website="https://other.example.test")

		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "website"), "https://profile.example.test")
		self.assertEqual(frappe.db.get_value("Partner", OTHER_PARTNER, "website"), "https://other.example.test")

	def test_customer_is_refused(self):
		frappe.set_user(BUYER)
		with self.assertRaises(frappe.PermissionError):
			get_my_profile()

	def test_member_also_on_a_customer_team_gets_their_partner(self):
		make_buyer(MEMBER, "_Test Profile Buyer Co")
		frappe.set_user(MEMBER)
		self.assertEqual(get_my_profile()["partner"], PARTNER)

	def test_removed_member_is_refused(self):
		frappe.db.set_value("Connect Partner Member", {"partner": PARTNER, "user": MEMBER}, "is_removed", 1)
		frappe.set_user(MEMBER)
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

	def test_picked_industries_earn_a_tick_from_two_stories(self):
		make_industries()
		frappe.set_user(ADMIN)
		stories = [
			{"client_name": "Refex", "headline": "Refex story", "category": "Textile Manufacturing"},
			{"client_name": "Motovolt", "headline": "Motovolt story", "category": "Textile Manufacturing"},
			{"client_name": "Kestrel", "headline": "Kestrel story", "category": "Agriculture"},
			{"client_name": "Orenda", "headline": "Orenda story", "category": "Agriculture"},
			{"client_name": "Halcyon", "headline": "Halcyon story", "category": "Retail"},
		]
		update_my_partner_profile(industries=["Textile Manufacturing", "Retail"], success_stories=stories)

		profile = get_my_profile()
		self.assertEqual(profile["industries"], ["Textile Manufacturing", "Retail"])
		self.assertEqual(
			[(badge["industry"], badge["stories"], badge["verified"]) for badge in profile["industry_badges"]],
			[("Textile Manufacturing", 2, True), ("Retail", 1, False)],
		)
		# proven by stories but not picked: offered in the edit dialog
		self.assertEqual(profile["suggested_industries"], [{"industry": "Agriculture", "stories": 2}])

	def test_at_most_six_industries(self):
		make_industries()
		frappe.set_user(ADMIN)
		with self.assertRaises(frappe.ValidationError):
			update_my_partner_profile(industries=INDUSTRY_NAMES[:7])
		update_my_partner_profile(industries=INDUSTRY_NAMES[:6])
		self.assertEqual(len(get_my_profile()["industries"]), 6)

	def test_gallery_holds_six_photos_and_two_videos(self):
		frappe.set_user(ADMIN)
		photos = [{"image": f"/files/photo-{n}.png"} for n in range(6)]
		videos = [{"image": f"/files/poster-{n}.png", "video": f"/files/video-{n}.mp4"} for n in range(3)]
		for too_many in (photos + [{"image": "/files/photo-6.png"}], photos[:1] + videos):
			with self.subTest(rows=len(too_many)), self.assertRaises(frappe.ValidationError):
				update_my_partner_profile(photos=too_many)

		update_my_partner_profile(photos=photos + videos[:2])
		self.assertEqual(len(get_my_profile()["photos"]), 8)

	def test_older_text_over_a_limit_does_not_block_other_changes(self):
		frappe.set_user(ADMIN)
		update_my_partner_profile(founder={"member_name": "Asha", "bio": "Short bio."})
		frappe.db.set_value("Partner Team Member", {"parent": PARTNER, "is_founder": 1}, "bio", "x" * 400)

		update_my_partner_profile(tagline="A new tagline", founder={"member_name": "Asha", "bio": "x" * 400})
		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "tagline"), "A new tagline")

		with self.assertRaises(frappe.ValidationError):
			update_my_partner_profile(founder={"member_name": "Asha", "bio": "y" * 400})


	def save_listing_section(self, **changes):
		"""Saves like a Listing dialog: the whole profile as the page shows it, with `changes`."""
		profile = get_my_profile(with_draft=True)
		fields = ("tagline", "description", "website", "address", "year_founded", "hourly_rate")
		payload = {field: profile[field] for field in fields}
		for field in ("apps", "migrations", "industries", "founder", "photos", "success_stories"):
			payload[field] = frappe.as_json(profile[field])
		update_my_partner_profile(**{**payload, **changes}, as_draft=1)

	def test_listing_edits_wait_until_published(self):
		frappe.set_user(ADMIN)
		self.save_listing_section(tagline="A drafted tagline")

		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "tagline"), "The live tagline")
		self.assertEqual(frappe.parse_json(frappe.db.get_value("Partner", PARTNER, "profile_draft")), {"tagline": "A drafted tagline"})
		profile = get_my_profile(with_draft=True)
		self.assertEqual(profile["tagline"], "A drafted tagline")
		self.assertTrue(profile["has_unpublished_changes"])
		self.assertEqual(get_my_profile()["tagline"], "The live tagline")

		publish_my_profile_draft()
		self.assertEqual(frappe.db.get_value("Partner", PARTNER, ["tagline", "profile_draft"]), ("A drafted tagline", None))
		self.assertFalse(get_my_profile(with_draft=True)["has_unpublished_changes"])

	def test_discard_drops_unpublished_changes(self):
		frappe.set_user(ADMIN)
		self.save_listing_section(tagline="A drafted tagline")
		discard_my_profile_draft()

		self.assertEqual(get_my_profile(with_draft=True)["tagline"], "The live tagline")
		with self.assertRaises(frappe.ValidationError):
			publish_my_profile_draft()

	def test_publish_keeps_a_desk_change_made_since(self):
		frappe.set_user(ADMIN)
		self.save_listing_section(tagline="A drafted tagline")
		frappe.db.set_value("Partner", PARTNER, "website", "https://desk.example.test")

		publish_my_profile_draft()
		saved = frappe.db.get_value("Partner", PARTNER, ["tagline", "website"])
		self.assertEqual(saved, ("A drafted tagline", "https://desk.example.test"))

	def test_drafts_are_checked_and_only_for_the_admin(self):
		frappe.set_user(ADMIN)
		with self.assertRaises(frappe.ValidationError):
			self.save_listing_section(tagline="x" * 81)
		with self.assertRaises(frappe.ValidationError):
			self.save_listing_section(country="Atlantis")
		self.assertIsNone(frappe.db.get_value("Partner", PARTNER, "profile_draft"))
		self.save_listing_section(tagline="A drafted tagline")

		frappe.set_user(MEMBER)
		for action in (publish_my_profile_draft, discard_my_profile_draft):
			with self.assertRaises(frappe.PermissionError):
				action()
		self.assertTrue(frappe.db.get_value("Partner", PARTNER, "profile_draft"))

	def test_partners_cannot_type_numbers_frappe_owns(self):
		owned = {"certs_erpnext": 0, "rollouts": 12, "sites_deployed": 30, "certified_experts": 4, "references_count": 5}
		frappe.db.set_value("Partner", PARTNER, dict(owned))
		frappe.set_user(ADMIN)

		# Through frappe.call, as the browser sends it, which drops arguments the API doesn't take.
		for as_draft in (0, 1):
			frappe.call(
				"connect.api.partner.update_my_partner_profile",
				**{field: 999 for field in owned}, tagline=f"Numbers come from Frappe {as_draft}", as_draft=as_draft,
			)
		publish_my_profile_draft()

		self.assertEqual(frappe.db.get_value("Partner", PARTNER, "tagline"), "Numbers come from Frappe 1")
		self.assertEqual(frappe.db.get_value("Partner", PARTNER, list(owned), as_dict=True), owned)
