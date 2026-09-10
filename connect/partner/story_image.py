# Copyright (c) 2026
# For license information, please see license.txt

"""Fetches each success story's own cover photo from its frappe.io page.

Every Partner Success Story links to a real https://frappe.io/stories/<slug>
page, and every one of those pages carries an og:image — the actual photo used
for that story, not a generic partner photo. This resolves that image once per
story and persists it on the row's `cover_image` field, so the profile page
never falls back to cycling through the partner's unrelated gallery photos.

Resolution happens in the background (see queue_story_image, called from
Partner.on_update) and via a one-time backfill (build_all_story_images) for
stories that already existed before this was added. A page read never scrapes
a story page itself — it only ever reads the persisted field.
"""

import re
import urllib.parse

import frappe

QUEUE_JOB_PREFIX = "partner-story-image::"
DOWNLOAD_TIMEOUT = 15
MAX_HTML_BYTES = 3 * 1024 * 1024

# frappe.io's markup has been observed with property/content in both orders
_OG_IMAGE_PATTERNS = (
	re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE),
	re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.IGNORECASE),
)


def _normalize_url(url: str) -> str:
	"""Percent-encodes a scraped URL's path/query, leaving scheme/host and any
	existing %XX escapes alone. og:image content attributes routinely contain
	literal spaces/parens straight from the filename (e.g. "logo (2).png"),
	which break both raw fetches and unquoted CSS url() usage downstream."""
	parts = urllib.parse.urlsplit(url)
	path = urllib.parse.quote(parts.path, safe="/%")
	query = urllib.parse.quote(parts.query, safe="=&%")
	return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def fetch_og_image(story_url: str) -> str | None:
	"""Fetches story_url and returns its og:image URL, or None."""
	if not story_url or not story_url.startswith(("http://", "https://")):
		return None

	import requests

	try:
		response = requests.get(
			story_url,
			timeout=DOWNLOAD_TIMEOUT,
			stream=True,
			headers={"User-Agent": "Mozilla/5.0 (compatible; FrappeConnect/1.0)"},
		)
		response.raise_for_status()
		# decode_content=True is required here: reading .raw directly otherwise
		# returns the raw (often gzip-compressed) transfer bytes unchanged, not
		# the decoded HTML — every og:image lookup silently failed without it.
		html = response.raw.read(MAX_HTML_BYTES + 1, decode_content=True).decode("utf-8", "ignore")
	except Exception:
		frappe.log_error(title="Connect: could not fetch success story page", message=frappe.get_traceback())
		return None

	for pattern in _OG_IMAGE_PATTERNS:
		match = pattern.search(html)
		if match:
			return _normalize_url(match.group(1))
	return None


def build_story_image(row_name: str, story_url: str) -> str | None:
	"""Fetches and persists one Partner Success Story row's cover_image.

	Safe to call repeatedly — no-ops once cover_image is already set, so a
	duplicate/stale queued job can never overwrite a value someone edited by
	hand in the meantime.
	"""
	existing = frappe.db.get_value("Partner Success Story", row_name, "cover_image")
	if existing:
		return existing

	image_url = fetch_og_image(story_url)
	if image_url:
		frappe.db.set_value("Partner Success Story", row_name, "cover_image", image_url, update_modified=False)
		frappe.db.commit()
	return image_url


def queue_story_image(row_name: str, story_url: str) -> None:
	"""Enqueues a background fetch — never called from a request that a guest is waiting on."""
	try:
		frappe.enqueue(
			"connect.partner.story_image.build_story_image",
			row_name=row_name,
			story_url=story_url,
			queue="short",
			job_id=f"{QUEUE_JOB_PREFIX}{row_name}",
			deduplicate=True,
		)
	except Exception:
		pass


def queue_missing_story_images(success_stories) -> None:
	"""Queues a fetch for every row that has a url but no cover_image yet.

	Called from Partner.on_update so newly added/edited success stories get
	their cover image resolved without anyone having to remember to run the
	backfill again.
	"""
	for row in success_stories or []:
		url = row.get("url") if isinstance(row, dict) else getattr(row, "url", None)
		cover_image = row.get("cover_image") if isinstance(row, dict) else getattr(row, "cover_image", None)
		name = row.get("name") if isinstance(row, dict) else getattr(row, "name", None)
		if url and not cover_image and name:
			queue_story_image(name, url)


def build_all_story_images():
	"""Backfills cover_image for every existing Partner Success Story row that
	has a url but no cover_image yet.

	Run with:
	    bench --site <site> execute connect.partner.story_image.build_all_story_images
	"""
	rows = frappe.get_all(
		"Partner Success Story",
		fields=["name", "url", "client_name"],
		filters={"url": ["is", "set"], "cover_image": ["in", ["", None]]},
		limit_page_length=0,
	)
	built, skipped = 0, 0
	for row in rows:
		if build_story_image(row.name, row.url):
			built += 1
		else:
			skipped += 1
	print(f"fetched {built} cover image(s), {skipped} left blank, out of {len(rows)}")
	return {"built": built, "skipped": skipped, "total": len(rows)}
