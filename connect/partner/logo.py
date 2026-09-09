# Copyright (c) 2026
# For license information, please see license.txt

"""Normalizes partner client logos into a consistent greyscale form.

Client logos are whatever files partners happened to upload, and they come in
four incompatible shapes: dark artwork on transparency, dark artwork baked onto
an opaque white box, artwork on an opaque dark box, and *light* artwork on
transparency. A plain CSS `grayscale()` filter only works for the first two —
light-on-transparent artwork stays white and renders invisible on the white
profile page, and dark-box logos turn into grey slabs.

There is no CSS-only fix: `mask-image` would rescue the transparent logos but
turn every opaque one into a solid rectangle. So the images themselves get
normalized here — inverted when they're light, background-stripped when they're
boxed, desaturated, and trimmed — and cached as PNGs under
`public/files/partner-logos/`, keyed by a hash of the source URL.

Anything that can't be processed (SVG, an unreachable URL, a corrupt file)
falls back to the original URL, which the page still renders behind its own
`grayscale()` filter. Nothing here raises into a page load.
"""

import hashlib
import io
import os

import frappe

CACHE_FOLDER = "partner-logos"
CACHE_URL_PREFIX = f"/files/{CACHE_FOLDER}"

DOWNLOAD_TIMEOUT = 15
MAX_SOURCE_BYTES = 8 * 1024 * 1024

# alpha above which a pixel counts as "artwork" rather than background
OPAQUE_ALPHA = 25
# mean luminance above which artwork counts as "light" and needs inverting.
# Sampled against the real logo set: genuine light logos measure 185-227,
# while dark artwork sits far below this.
LIGHT_ARTWORK_LUMA = 170
# luminance bands for classifying an opaque image's background colour
WHITE_BG_LUMA = 225
DARK_BG_LUMA = 90
# how close a pixel must be to the detected background colour to be knocked out
BG_COLOR_TOLERANCE = 32


def _cache_key(source_url: str) -> str:
	return hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:16]


def _cache_paths(source_url: str):
	name = f"{_cache_key(source_url)}.png"
	folder = frappe.get_site_path("public", "files", CACHE_FOLDER)
	return os.path.join(folder, name), f"{CACHE_URL_PREFIX}/{name}"


def cached_logo_url(source_url: str) -> str | None:
	"""Returns the normalized URL only if it's already on disk, else None.

	Read paths use this so a guest page load never triggers an outbound fetch.
	"""
	if not source_url:
		return None
	path, url = _cache_paths(source_url)
	return url if os.path.exists(path) else None


def _read_source(source_url: str) -> bytes | None:
	"""Fetches the source image, reading local site files straight off disk."""
	if source_url.startswith("/files/") or source_url.startswith("/private/files/"):
		relative = source_url.lstrip("/")
		base = "public" if source_url.startswith("/files/") else ""
		path = frappe.get_site_path(base, relative) if base else frappe.get_site_path(relative)
		if not os.path.exists(path):
			return None
		with open(path, "rb") as f:
			return f.read(MAX_SOURCE_BYTES + 1)

	if not source_url.startswith(("http://", "https://")):
		return None

	import requests

	response = requests.get(
		source_url,
		timeout=DOWNLOAD_TIMEOUT,
		stream=True,
		headers={"User-Agent": "Mozilla/5.0 (compatible; FrappeConnect/1.0)"},
	)
	response.raise_for_status()
	# decode_content=True: reading .raw directly otherwise returns the raw
	# transfer-encoded bytes unchanged if the server gzips the response, not the
	# actual image bytes (caught this the hard way in story_image.py's HTML
	# fetch — images usually aren't gzipped, but nothing guarantees it here).
	return response.raw.read(MAX_SOURCE_BYTES + 1, decode_content=True)


def _luma(pixel) -> float:
	return 0.299 * pixel[0] + 0.587 * pixel[1] + 0.114 * pixel[2]


def _background_color(image):
	"""Guesses an opaque image's background from its four border strips."""
	width, height = image.size
	edge = []
	for x in range(width):
		edge.append(image.getpixel((x, 0)))
		edge.append(image.getpixel((x, height - 1)))
	for y in range(height):
		edge.append(image.getpixel((0, y)))
		edge.append(image.getpixel((width - 1, y)))

	# the modal edge colour, so a logo that bleeds into one edge doesn't win
	counts = {}
	for pixel in edge:
		key = (pixel[0] // 8, pixel[1] // 8, pixel[2] // 8)
		counts[key] = counts.get(key, 0) + 1
	modal = max(counts, key=counts.get)
	return (modal[0] * 8 + 4, modal[1] * 8 + 4, modal[2] * 8 + 4)


def _knock_out_background(image, bg_color):
	"""Makes pixels within tolerance of bg_color transparent."""
	from PIL import Image

	width, height = image.size
	pixels = list(image.getdata())
	out = []
	br, bg, bb = bg_color
	for r, g, b, a in pixels:
		if abs(r - br) <= BG_COLOR_TOLERANCE and abs(g - bg) <= BG_COLOR_TOLERANCE and abs(b - bb) <= BG_COLOR_TOLERANCE:
			out.append((r, g, b, 0))
		else:
			out.append((r, g, b, a))
	result = Image.new("RGBA", (width, height))
	result.putdata(out)
	return result


def _normalize(raw: bytes):
	"""Returns normalized PNG bytes, or None if the image can't be processed."""
	from PIL import Image, ImageOps

	image = Image.open(io.BytesIO(raw))
	image = image.convert("RGBA")

	pixels = list(image.getdata())
	has_alpha = any(p[3] < 250 for p in pixels)
	artwork = [p for p in pixels if p[3] > OPAQUE_ALPHA]
	if not artwork:
		return None

	if has_alpha:
		# transparent-backed: invert only if the artwork itself is light, so it
		# stops being white-on-white
		if sum(_luma(p) for p in artwork) / len(artwork) > LIGHT_ARTWORK_LUMA:
			rgb = ImageOps.invert(image.convert("RGB"))
			image = Image.merge("RGBA", (*rgb.split(), image.split()[3]))
	else:
		# opaque: strip the box so it sits on the page like the others do
		bg = _background_color(image)
		bg_luma = _luma(bg)
		if bg_luma < DARK_BG_LUMA:
			# dark box — invert so the artwork goes dark and the box goes light,
			# then knock the (now light) box out
			image = ImageOps.invert(image.convert("RGB")).convert("RGBA")
			bg = tuple(255 - c for c in bg)
			image = _knock_out_background(image, bg)
		elif bg_luma > WHITE_BG_LUMA:
			image = _knock_out_background(image, bg)

	# desaturate, keeping the alpha channel intact
	alpha = image.split()[3]
	grey = image.convert("L").convert("RGB")
	image = Image.merge("RGBA", (*grey.split(), alpha))

	# trim transparent padding so every logo has the same optical weight in the
	# row instead of inheriting whatever whitespace was baked into the upload
	bbox = image.getbbox()
	if bbox:
		image = image.crop(bbox)

	buffer = io.BytesIO()
	image.save(buffer, format="PNG", optimize=True)
	return buffer.getvalue()


def build_logo(source_url: str) -> str | None:
	"""Normalizes one logo and writes it to the cache. Returns its URL, or None.

	Safe to call repeatedly — it no-ops once the file exists.
	"""
	if not source_url:
		return None

	path, url = _cache_paths(source_url)
	if os.path.exists(path):
		return url

	try:
		raw = _read_source(source_url)
		if not raw or len(raw) > MAX_SOURCE_BYTES:
			return None
		normalized = _normalize(raw)
		if not normalized:
			return None
		os.makedirs(os.path.dirname(path), exist_ok=True)
		with open(path, "wb") as f:
			f.write(normalized)
		return url
	except Exception:
		# a bad logo must never break a partner profile
		frappe.log_error(title="Connect: could not normalize partner logo", message=frappe.get_traceback())
		return None


def attach_normalized_logos(success_stories) -> None:
	"""Adds `client_logo_display` to each success story row, in place.

	Uses the cache only. A logo that hasn't been built yet falls back to its
	original URL and is queued for background normalization, so page loads stay
	fast and never depend on an outbound request.
	"""
	pending = []
	for row in success_stories or []:
		source = row.get("client_logo") if isinstance(row, dict) else getattr(row, "client_logo", None)
		if not source:
			continue
		display = cached_logo_url(source)
		if not display:
			display = source
			pending.append(source)
		if isinstance(row, dict):
			row["client_logo_display"] = display
		else:
			row.client_logo_display = display

	for source in dict.fromkeys(pending):
		try:
			frappe.enqueue(
				"connect.partner.logo.build_logo",
				source_url=source,
				queue="short",
				job_id=f"partner-logo::{_cache_key(source)}",
				deduplicate=True,
			)
		except Exception:
			pass


def build_all_logos():
	"""Warms the cache for every client logo on record.

	Run with:
	    bench --site <site> execute connect.partner.logo.build_all_logos
	"""
	rows = frappe.get_all(
		"Partner Success Story",
		fields=["client_logo"],
		filters={"client_logo": ["is", "set"]},
		limit_page_length=0,
	)
	sources = list(dict.fromkeys(r.client_logo for r in rows if r.client_logo))
	built, skipped = 0, 0
	for source in sources:
		if build_logo(source):
			built += 1
		else:
			skipped += 1
	print(f"normalized {built} logo(s), {skipped} left on their original URL, out of {len(sources)}")
	return {"built": built, "skipped": skipped, "total": len(sources)}
