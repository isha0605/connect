# Copyright (c) 2026
# For license information, please see license.txt

from datetime import date

import frappe
from frappe import _
from frappe.utils import add_days, cint, escape_html, getdate

from connect.partner.doctype.partner.partner import VERIFIED
from connect.partner.doctype.partner_tier.tier_review import (
	ENTRY,
	TierLadder,
	email_partner_admins,
	is_applying_changes,
)

SHOW = "Show"
HIDE = "Hide"
# A listed partner short of certificates has this long, from Listed On, to certify someone new.
LISTING_GRACE_DAYS = 90
PARTNER_FIELDS = [
	"name", "tier", "show_in_website", "listed_on", "keep_listing", "erpnext_certified", "framework_certified",
]


def review_partner_listings() -> None:
	"""Decides who the partner directory shows: an approved partner with the certificates its tier
	needs. Runs after the tier review, so certificates are checked against the current tier. A partner
	that fails is logged and the rest carry on."""
	ladder = TierLadder()
	apply_changes = is_applying_changes()
	partners = frappe.get_all(
		"Partner", filters={"enabled": 1, "verification_status": VERIFIED}, fields=PARTNER_FIELDS
	)

	for partner in partners:
		frappe.db.savepoint("listing_review")
		try:
			review_listing(ladder, partner, apply_changes)
		except Exception:
			frappe.db.rollback(save_point="listing_review")
			frappe.log_error(title=f"Listing review failed for {partner.name}")


def review_listing(ladder: TierLadder, partner: frappe._dict, apply_changes: bool) -> None:
	"""Saves whether the partner should be shown, and shows or hides it when listing changes are on and
	its listing isn't kept."""
	listing = get_listing(ladder, partner)
	frappe.db.set_value("Partner", partner.name, "listing_review", listing, update_modified=False)

	is_shown = bool(partner.show_in_website)
	if apply_changes and not partner.keep_listing and (listing == SHOW) != is_shown:
		change_listing(ladder, partner.name, show=listing == SHOW)


def get_listing(ladder: TierLadder, partner: frappe._dict, on: date | None = None) -> str:
	"""Show a partner with the certificates its tier needs. A listed partner that falls short stays
	shown until 90 days after it was listed."""
	if get_certificate_count(partner) >= get_certificates_needed(ladder, partner.tier):
		return SHOW

	if not partner.show_in_website:
		return HIDE
	listed_on = getdate(partner.listed_on or on)
	return HIDE if listed_on <= add_days(getdate(on), -LISTING_GRACE_DAYS) else SHOW


def get_certificates_needed(ladder: TierLadder, tier: str) -> int:
	"""The tier's certificate count, but never less than Entry's: Beginner needs none to hold its tier,
	yet a partner in the directory must have certified people."""
	return max(cint(ladder.get(tier).certificates_required), cint(ladder.get(ENTRY).certificates_required))


def get_certificate_count(partner) -> int:
	return cint(partner.erpnext_certified) + cint(partner.framework_certified)


def change_listing(ladder: TierLadder, partner: str, show: bool) -> None:
	doc = frappe.get_doc("Partner", partner)
	doc.show_in_website = int(show)
	# The daily review runs for Frappe, not for a signed-in user: the listing is Frappe's to set.
	doc.save(ignore_permissions=True)
	subject, message = _listed_email(doc) if show else _hidden_email(ladder, doc)
	email_partner_admins(doc.name, subject, message)


def _listed_email(doc) -> tuple[str, str]:
	name = escape_html(doc.company_name)
	listed = _("Customers can now find {0} in the Frappe partner directory.").format(name)
	subject = _("{0} is now in the Frappe partner directory").format(doc.company_name)
	return subject, f"<p>{listed}</p>"


def _hidden_email(ladder: TierLadder, doc) -> tuple[str, str]:
	"""Says how many certificates the partner has and needs, so it knows how to come back."""
	name = escape_html(doc.company_name)
	short = _("{0} has {1} certified team members, and a {2} partner in the directory needs {3}.").format(
		name, get_certificate_count(doc), doc.tier, get_certificates_needed(ladder, doc.tier)
	)
	back = _("Add certified team members and {0} is listed again at the next daily review.").format(name)
	subject = _("{0} has been taken off the Frappe partner directory").format(doc.company_name)
	return subject, f"<p>{short}</p><p>{back}</p>"
