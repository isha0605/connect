# Copyright (c) 2026
# For license information, please see license.txt

import html as html_entities
import re

import frappe

from connect.partner.story_image import fetch_story_page

QUEUE_JOB_PREFIX = "partner-story-apps::"
# Only frappe.io's own story pages carry an "Apps implemented" list.
STORY_PAGE_PREFIX = "https://frappe.io/stories/"

_APPS_HEADING = re.compile(r">\s*Apps implemented\s*<", re.IGNORECASE)
# The next heading on the page ("Industry") is a <p>; the app names are not.
_NEXT_HEADING = re.compile(r"<p[\s>]", re.IGNORECASE)
_TEXT = re.compile(r">([^<>]+)<")
# How far to read when the page has no heading after the apps.
MAX_SECTION_CHARS = 5000


def apps_in_story_page(page_html: str, known_apps: list[str]) -> list[str]:
	"""The Connect apps a frappe.io story page lists under "Apps implemented", each once.
	frappe.io writes some names with "Frappe" in front and some without, so either form matches."""
	heading = _APPS_HEADING.search(page_html or "")
	if not heading:
		return []

	next_heading = _NEXT_HEADING.search(page_html, heading.end())
	end = next_heading.start() if next_heading else heading.end() + MAX_SECTION_CHARS
	names = [html_entities.unescape(text).strip() for text in _TEXT.findall(page_html[heading.end() : end])]

	by_key = {_app_key(app): app for app in known_apps}
	found = [by_key.get(_app_key(name)) for name in names if name]
	return list(dict.fromkeys(app for app in found if app))


def _app_key(name: str) -> str:
	return name.strip().lower().removeprefix("frappe ").strip()


def apps_from_stories(stories) -> list[str]:
	"""Every app the partner's success stories name, each once, in story order."""
	apps = []
	for story in stories or []:
		apps.extend(line.strip() for line in (story.get("apps") or "").splitlines() if line.strip())
	return list(dict.fromkeys(apps))


def build_story_apps(row_name: str, story_url: str) -> list[str]:
	"""Fetches one story's page and saves the apps it lists on the Partner Success Story row."""
	page_html = fetch_story_page(story_url)
	if not page_html:
		return []

	apps = apps_in_story_page(page_html, frappe.get_all("App", pluck="name"))
	if apps:
		frappe.db.set_value("Partner Success Story", row_name, "apps", "\n".join(apps), update_modified=False)
		frappe.db.commit()  # nosemgrep: the backfill fetches a page per row; keep each row's apps if the run stops partway
	return apps


def queue_missing_story_apps(success_stories) -> None:
	"""Queues a background fetch for each frappe.io story that has no apps saved yet."""
	for story in success_stories or []:
		url = story.get("url") or ""
		if not url.startswith(STORY_PAGE_PREFIX) or story.get("apps") or not story.get("name"):
			continue
		# One failure usually means the job queue is down: stop, so the save logs it once.
		if not _queue_story_apps(story.get("name"), url):
			break


def _queue_story_apps(row_name: str, story_url: str) -> bool:
	try:
		frappe.enqueue(
			"connect.partner.story_apps.build_story_apps",
			row_name=row_name,
			story_url=story_url,
			queue="short",
			job_id=f"{QUEUE_JOB_PREFIX}{row_name}",
			deduplicate=True,
		)
	except Exception:
		frappe.log_error(title="Connect: could not queue a success story's apps")
		return False
	return True


def build_all_story_apps() -> dict:
	"""Fills the apps of every frappe.io story that has none yet. The data patch queues this once."""
	rows = frappe.get_all(
		"Partner Success Story",
		fields=["name", "url"],
		filters={"url": ["like", f"{STORY_PAGE_PREFIX}%"], "apps": ["in", ["", None]]},
		limit_page_length=0,
	)
	filled = sum(1 for row in rows if build_story_apps(row.name, row.url))
	return {"filled": filled, "total": len(rows)}
