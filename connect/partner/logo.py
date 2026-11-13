# Copyright (c) 2026
# For license information, please see license.txt

"""Normalizes partner client logos into a consistent greyscale form.

Client logos are whatever files partners happened to upload: dark artwork on
transparency, artwork baked onto a box of any colour (sometimes a box inside a
white margin), and *light* artwork on transparency. A plain CSS `grayscale()`
filter only works for the first — light artwork stays white and renders
invisible on the white profile page, and boxed logos turn into grey slabs.

There is no CSS-only fix: `mask-image` would rescue the transparent logos but
turn every opaque one into a solid rectangle. So the images themselves get
normalized here — boxes stripped, light artwork inverted, desaturated, and
trimmed — and cached as PNGs under `public/files/partner-logos-v2/`, keyed by a
hash of the source URL. Each PNG records its ink weight, which the page uses to
size the logos optically.

Anything that can't be processed (SVG, an unreachable URL, a corrupt file)
falls back to the original URL, which the page still renders behind its own
`grayscale()` filter. Nothing here raises into a page load.
"""

import hashlib
import io
import os

import frappe

# Renamed whenever normalizing changes, so every logo is rebuilt the new way.
CACHE_FOLDER = "partner-logos-v2"
CACHE_URL_PREFIX = f"/files/{CACHE_FOLDER}"

DOWNLOAD_TIMEOUT = 15
MAX_SOURCE_BYTES = 8 * 1024 * 1024

# alpha above which a pixel counts as "artwork" rather than background
OPAQUE_ALPHA = 25
# mean luminance above which artwork counts as "light" and needs inverting.
# Sampled against the real logo set: genuine light logos measure 185-227,
# while dark artwork sits far below this.
LIGHT_ARTWORK_LUMA = 170
# how close a pixel must be to the detected background colour to be knocked out
BG_COLOR_TOLERANCE = 32
# a box is a border mostly visible (not transparent) and mostly one colour
BOX_VISIBLE_SHARE = 0.5
BOX_COLOR_SHARE = 0.8
# a white margin around a coloured box takes two passes
MAX_BOXES = 2
# the PNG text key holding the share of the trimmed logo that is artwork
INK_KEY = "ink"


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


def _border_points(image) -> list:
	width, height = image.size
	return [(x, y) for x in range(width) for y in (0, height - 1)] + [
		(x, y) for y in range(height) for x in (0, width - 1)
	]


def _modal_color(pixels):
	"""The commonest colour, so a logo that bleeds into one edge doesn't win."""
	counts = {}
	for pixel in pixels:
		key = (pixel[0] // 8, pixel[1] // 8, pixel[2] // 8)
		counts[key] = counts.get(key, 0) + 1
	modal = max(counts, key=counts.get)
	return (modal[0] * 8 + 4, modal[1] * 8 + 4, modal[2] * 8 + 4)


def _is_near(pixel, color) -> bool:
	return all(abs(pixel[channel] - color[channel]) <= BG_COLOR_TOLERANCE for channel in range(3))


def _strip_box(image):
	"""Makes a solid box transparent and trims to what's left. Returns the image and
	whether there was a box: a border mostly visible and mostly one colour, with
	artwork inside (a logo that is only a solid shape stays). Only the box reached
	from the edge goes, so artwork of the same colour inside it stays."""
	from PIL import ImageDraw

	points = _border_points(image)
	border = [image.getpixel(point) for point in points]
	visible = [pixel for pixel in border if pixel[3] > OPAQUE_ALPHA]
	if len(visible) < BOX_VISIBLE_SHARE * len(border):
		return image, False

	box = _modal_color(visible)
	if sum(_is_near(pixel, box) for pixel in visible) < BOX_COLOR_SHARE * len(visible):
		return image, False

	result = image.copy()
	for point in points:
		pixel = result.getpixel(point)
		if pixel[3] > OPAQUE_ALPHA and _is_near(pixel, box):
			ImageDraw.floodfill(result, point, (0, 0, 0, 0), thresh=3 * BG_COLOR_TOLERANCE)
	if not result.getbbox():
		return image, False
	return _trim(result), True


def _trim(image):
	"""Crops transparent padding, so every logo has the same optical weight in the row
	instead of inheriting whatever whitespace was baked into the upload."""
	bbox = image.getbbox()
	return image.crop(bbox) if bbox else image


def _ink(image) -> float:
	alpha = image.split()[3].getdata()
	return sum(1 for value in alpha if value > OPAQUE_ALPHA) / len(alpha)


def _normalize(raw: bytes):
	"""Returns normalized PNG bytes, or None if the image can't be processed."""
	from PIL import Image, ImageOps, PngImagePlugin

	image = _trim(Image.open(io.BytesIO(raw)).convert("RGBA"))
	for _pass in range(MAX_BOXES):
		image, has_box = _strip_box(image)
		if not has_box:
			break

	artwork = [pixel for pixel in image.getdata() if pixel[3] > OPAQUE_ALPHA]
	if not artwork:
		return None

	# light artwork (often what a dark box held) is inverted, so it isn't white-on-white
	if sum(_luma(pixel) for pixel in artwork) / len(artwork) > LIGHT_ARTWORK_LUMA:
		rgb = ImageOps.invert(image.convert("RGB"))
		image = Image.merge("RGBA", (*rgb.split(), image.split()[3]))

	# desaturate, keeping the alpha channel intact
	alpha = image.split()[3]
	grey = image.convert("L").convert("RGB")
	image = _trim(Image.merge("RGBA", (*grey.split(), alpha)))

	info = PngImagePlugin.PngInfo()
	info.add_text(INK_KEY, f"{_ink(image):.3f}")
	buffer = io.BytesIO()
	image.save(buffer, format="PNG", optimize=True, pnginfo=info)
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


def get_logo_shape(source_url: str) -> dict:
	"""A built logo's width-to-height ratio and ink weight, which the page sizes it by.
	Reads only the PNG's header. Empty for a logo not built yet."""
	from PIL import Image

	path, _url = _cache_paths(source_url)
	try:
		with Image.open(path) as image:
			return {
				"client_logo_ratio": round(image.width / image.height, 3),
				"client_logo_ink": float(image.info[INK_KEY]),
			}
	except (OSError, KeyError, ValueError):
		return {}


def attach_normalized_logos(success_stories) -> None:
	"""Adds `client_logo_display` to each success story row, in place, and the
	logo's shape (see get_logo_shape) once it's built.

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
		shape = get_logo_shape(source) if display else {}
		if not display:
			display = source
			pending.append(source)
		values = {"client_logo_display": display, **shape}
		if isinstance(row, dict):
			row.update(values)
		else:
			for key, value in values.items():
				setattr(row, key, value)

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
			# Usually the job queue is down, so the rest would fail too: log once and show the
			# original logos. Deferred, as a page load's writes are rolled back.
			frappe.log_error(title="Connect: could not queue partner logo builds", defer_insert=True)
			break


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
