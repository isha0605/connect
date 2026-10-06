# Copyright (c) 2026
# For license information, please see license.txt

"""PMM levels from Frappe's public partner listing.

Frappe's partner team rates each partner on the Process Maturity Model, Level 1 to 5
(frappe.io/partners/maturity-model), and shows it on the partner's page at
frappe.io/partners/<country>/<partner>: an image named pml-<level>.svg, or "TBD" while the
partner isn't rated yet. There's no API for it, so this reads those pages.

The pages are a website, not a contract. A page whose rating can't be read is skipped,
never written as 0, and the run reports it. A partner is matched to its page once by name,
then by the page link kept on the Partner.

Run it with: bench --site <site> execute connect.partner.pmm_sync.sync_pmm_levels
"""

import re
import time
from urllib.parse import unquote_plus

import frappe
import requests
from frappe.utils import cint

LISTING_URL = "https://frappe.io/partners/list"
PAGE_LINK = re.compile(r'href="(https://frappe\.io/partners/[a-z-]+/[^"?#/]+)"')
# The first rating after the MATURITY label: the level's image, or TBD.
RATING = re.compile(r"MATURITY.{0,4000}?(?:/files/pml-([1-5])\.svg|>\s*(TBD)\s*<)", re.S)
CONTACT_NAME = re.compile(r'contact-partner/new\?partner=([^&"]+)')
HEADER_NAME = re.compile(r'</section><div class="[^"]*"><div class="[^"]*__text_block__">([^<]+)</div>')
HEADERS = {"User-Agent": "Frappe Connect PMM sync"}
PAUSE_SECONDS = 0.3

# Left out when comparing names, so "Tridots Tech" matches "Tridots Tech Private Limited".
NAME_NOISE = re.compile(
	r"\b(private limited|pvt\.? ltd\.?|pvt|pte\.? ltd\.?|ltd\.?|limited|llp|inc\.?|incorporation|llc|fze|fzc|"
	r"wll|co\.?|company|gmbh|bv|pty|plc|opc|the|solutions?|technologies|technology|tech|software|services|"
	r"systems|consult(ing|ancy)?|global|infotech|infosystems|it)\b"
)


def sync_pmm_levels(dry_run=False):
	"""Read every partner's PMM level from frappe.io and update the ones that changed.
	Returns what happened, for the person running it."""
	pages = [read_page(url) for url in listing_urls()]
	partners = frappe.get_all("Partner", fields=["name", "country", "pmm_level", "pmm_listing_url"])
	matches = match_partners(partners, pages)

	report = frappe._dict(updated=[], unchanged=0, unreadable=[], not_on_frappe_io=[], not_on_connect=[])
	matched_urls = set()
	for partner in partners:
		page = matches.get(partner.name)
		if not page:
			report.not_on_frappe_io.append(partner.name)
			continue
		matched_urls.add(page.url)
		if page.level is None:
			report.unreadable.append(page.url)
			continue
		if cint(partner.pmm_level) == page.level and partner.pmm_listing_url == page.url:
			report.unchanged += 1
			continue
		report.updated.append(f"{partner.name}: {cint(partner.pmm_level)} -> {page.level}")
		if not dry_run:
			frappe.db.set_value(
				"Partner", partner.name, {"pmm_level": page.level, "pmm_listing_url": page.url}, update_modified=False
			)

	report.not_on_connect = sorted(p.names[0] for p in pages if p.url not in matched_urls)
	if not dry_run:
		frappe.db.commit()
	return report


def listing_urls():
	html = fetch(LISTING_URL)
	return sorted(set(PAGE_LINK.findall(html)))


def read_page(url):
	time.sleep(PAUSE_SECONDS)  # one page at a time, gently
	return parse_page(url, fetch(url))


def fetch(url):
	response = requests.get(url, headers=HEADERS, timeout=30)
	response.raise_for_status()
	return response.text


def parse_page(url, html):
	"""A partner page as {url, country, names, level}. level is 0 for TBD (not rated yet) and
	None when the page shows neither, so a markup change never wipes a level."""
	names = [unquote_plus(m).strip() for m in CONTACT_NAME.findall(html)[:1]]
	names += [m.strip() for m in HEADER_NAME.findall(html)[:1]]
	rating = RATING.search(html)
	level = None
	if rating:
		level = int(rating.group(1)) if rating.group(1) else 0
	return frappe._dict(
		url=url,
		country=url.split("/partners/")[1].split("/")[0].replace("-", " "),
		names=[n for n in names if n] or [url.rsplit("/", 1)[1]],
		level=level,
	)


def match_partners(partners, pages):
	"""{partner name: page}. A partner keeps the page it was matched to before; otherwise
	its name is compared with the page's names, and the country decides between two."""
	by_url = {p.url: p for p in pages}
	by_name = {}
	for page in pages:
		for name in page.names:
			by_name.setdefault(comparable(name), {})[page.url] = page

	matches = {}
	for partner in partners:
		if partner.pmm_listing_url in by_url:
			matches[partner.name] = by_url[partner.pmm_listing_url]
			continue
		candidates = list(by_name.get(comparable(partner.name), {}).values())
		if len(candidates) > 1:
			country = (partner.country or "").lower()
			candidates = [p for p in candidates if p.country in country or country in p.country] or candidates
		if len(candidates) == 1:
			matches[partner.name] = candidates[0]
	return matches


def comparable(name):
	name = (name or "").lower().replace("&", " and ")
	name = re.sub(r"\(.*?\)", " ", name)
	return re.sub(r"[^a-z0-9]", "", NAME_NOISE.sub(" ", name))
