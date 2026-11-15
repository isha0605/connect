# Copyright (c) 2026
# For license information, please see license.txt

from collections.abc import Callable

import frappe
from frappe import _
from frappe.utils import cint, escape_html, flt, fmt_money, getdate, today

from connect.partner.doctype.partner.partner import VERIFIED
from connect.permissions import _get_partner_owners

BEGINNER = "Beginner"
ENTRY = "Entry"
# PMM only holds back a move up past this tier: frappe.io lets a partner reach Emerging on revenue and
# certificates alone.
PMM_FREE_UP_TO = "Emerging"
TIER_EMAIL_CC = "partner@frappe.io"
PARTNER_FIELDS = [
	"name", "partner_name", "tier", "currency", "keep_tier", "pmm_level",
	"certs_erpnext", "certs_frappe_framework", "revenue_last_month", "revenue_this_month", "revenue_updated_on",
]


class TierLadder:
	"""Every partner tier, highest first, with ways to compare two of them."""

	def __init__(self):
		self.tiers = frappe.get_all(
			"Partner Tier",
			fields=["name", "enabled", "target_in_inr", "target_in_usd", "certificates_required", "pmm_required"],
			order_by="target_in_inr desc, certificates_required desc",
		)
		self.rank = {tier.name: position for position, tier in enumerate(self.tiers)}

	def get(self, name: str) -> frappe._dict:
		return self.tiers[self.rank[name]]

	def is_above(self, tier: str, other: str) -> bool:
		return self.rank[tier] < self.rank[other]

	def higher(self, *tiers: str) -> str:
		return min(tiers, key=self.rank.__getitem__)

	def lower(self, *tiers: str) -> str:
		return max(tiers, key=self.rank.__getitem__)

	def highest_met(self, is_met: Callable[[frappe._dict], bool]) -> str | None:
		return next((tier.name for tier in self.tiers if tier.enabled and is_met(tier)), None)


def is_applying_changes() -> bool:
	"""Whether the daily review may change tiers and listings, or only show what it would do."""
	return bool(cint(frappe.db.get_single_value("Integration Settings", "apply_tier_and_listing_changes")))


def review_partner_tiers() -> None:
	"""Reviews every approved partner's tier. A partner that fails is logged and the rest carry on."""
	ladder = TierLadder()
	apply_changes = is_applying_changes()
	partners = frappe.get_all(
		"Partner", filters={"enabled": 1, "verification_status": VERIFIED}, fields=PARTNER_FIELDS
	)

	for partner in partners:
		frappe.db.savepoint("tier_review")
		try:
			review_partner(ladder, partner, apply_changes)
		except Exception:
			frappe.db.rollback(save_point="tier_review")
			frappe.log_error(title=f"Tier review failed for {partner.name}")


def review_partner(ladder: TierLadder, partner: frappe._dict, apply_changes: bool) -> None:
	"""Saves the tier the partner earns (and the one this month points to), and moves it there when
	tier changes are on and its tier isn't kept."""
	# Revenue not read today is unknown: the partner may then only move up to Entry, never down.
	revenue_is_known = bool(partner.revenue_updated_on) and getdate(partner.revenue_updated_on) == getdate()
	certificates = cint(partner.certs_erpnext) + cint(partner.certs_frappe_framework)

	def earned_with(revenue):
		known_revenue = revenue if revenue_is_known else None
		return get_earned_tier(
			ladder, partner.tier, known_revenue, partner.currency, certificates, partner.pmm_level
		)

	reviewed_tier = earned_with(partner.revenue_last_month)
	frappe.db.set_value(
		"Partner",
		partner.name,
		{"reviewed_tier": reviewed_tier, "next_tier": earned_with(partner.revenue_this_month)},
		update_modified=False,
	)
	if apply_changes and not partner.keep_tier and reviewed_tier != partner.tier:
		change_tier(ladder, partner.name, reviewed_tier)


def get_earned_tier(
	ladder: TierLadder, current: str, revenue: float | None, currency: str, certificates: int, pmm: float
) -> str:
	"""The tier a partner earns, by frappe.io's rules: the lower of the tier its revenue reaches and the
	tier its certificates reach, held back by PMM. A partner at Entry or above never drops below Entry.
	With unknown revenue (None) a partner never moves down and can move up to Entry at most."""
	target_field = "target_in_inr" if currency == "INR" else "target_in_usd"
	if revenue is None:
		revenue_tier = ENTRY
	else:
		revenue_tier = ladder.highest_met(
			lambda tier: tier.name != BEGINNER and flt(revenue) >= flt(tier[target_field])
		)
	certificate_tier = ladder.highest_met(lambda tier: cint(certificates) >= cint(tier.certificates_required))

	earned = ladder.lower(revenue_tier or current, certificate_tier or current)
	earned = _hold_back_by_pmm(ladder, earned, current, pmm)
	if current != BEGINNER:
		earned = ladder.higher(earned, ENTRY)
	if revenue is None:
		earned = ladder.higher(earned, current)
	return earned


def _hold_back_by_pmm(ladder: TierLadder, earned: str, current: str, pmm: float) -> str:
	"""PMM never moves a partner down. It only holds back a move up past Emerging, to the highest of the
	current tier, the tier the PMM level reaches, and Emerging."""
	if not ladder.is_above(earned, ladder.higher(current, PMM_FREE_UP_TO)):
		return earned

	pmm_tier = ladder.highest_met(lambda tier: flt(pmm) >= flt(tier.pmm_required)) or current
	if not ladder.is_above(earned, pmm_tier):
		return earned
	return ladder.higher(current, pmm_tier, PMM_FREE_UP_TO)


def change_tier(ladder: TierLadder, partner: str, new_tier: str) -> None:
	doc = frappe.get_doc("Partner", partner)
	old_tier = doc.tier
	doc.update({"tier": new_tier, "previous_tier": old_tier, "tier_changed_on": today()})
	# The daily review runs for Frappe, not for a signed-in user: the tier is Frappe's to set.
	doc.save(ignore_permissions=True)
	send_tier_email(ladder, doc, old_tier)


def send_tier_email(ladder: TierLadder, doc, old_tier: str) -> None:
	moved_up = ladder.is_above(doc.tier, old_tier)
	subject, message = (_upgrade_email if moved_up else _downgrade_email)(ladder, doc, old_tier)
	email_partner_admins(doc.name, subject, message)


def email_partner_admins(partner: str, subject: str, message: str) -> None:
	"""Emails the partner's admins, with the partnerships team in copy."""
	owners = _get_partner_owners(partner)
	recipients = frappe.get_all("User", filters={"name": ["in", owners or [""]]}, pluck="email")
	if not recipients:
		return

	frappe.sendmail(
		recipients=recipients,
		cc=[TIER_EMAIL_CC],
		subject=subject,
		message=message,
		reference_doctype="Partner",
		reference_name=partner,
	)


def _upgrade_email(ladder: TierLadder, doc, old_tier: str) -> tuple[str, str]:
	moved = _("Congratulations! {0} has moved from {1} to {2} in the Frappe Partner Program.").format(
		escape_html(doc.partner_name), old_tier, doc.tier
	)
	follows = _(
		"Your tier follows last month's revenue from your Frappe Cloud customers, your certified team "
		"members and your PMM level."
	)
	subject = _("{0} is now a {1} partner").format(doc.partner_name, doc.tier)
	return subject, f"<p>{moved}</p><p>{follows}</p>"


def _downgrade_email(ladder: TierLadder, doc, old_tier: str) -> tuple[str, str]:
	"""Shows what the old tier needs against what the partner has, so it knows what to work on."""
	needs = ladder.get(old_tier)
	target = needs.target_in_inr if doc.currency == "INR" else needs.target_in_usd
	rows = (
		(
			_("Revenue last month"),
			fmt_money(target, currency=doc.currency),
			fmt_money(doc.revenue_last_month, currency=doc.currency),
		),
		(
			_("Certified team members"),
			cint(needs.certificates_required),
			cint(doc.certs_erpnext) + cint(doc.certs_frappe_framework),
		),
		(_("PMM level"), flt(needs.pmm_required), flt(doc.pmm_level)),
	)
	items = "".join(
		"<li>{0}: {1}</li>".format(label, _("{0} needed, you have {1}").format(needed, has))
		for label, needed, has in rows
	)

	moved = _("{0} has moved from {1} to {2} in the Frappe Partner Program.").format(
		escape_html(doc.partner_name), old_tier, doc.tier
	)
	needed = _("A {0} partner needs:").format(old_tier)
	again = _("Once you reach these again, your tier moves back up at the next daily review.")
	subject = _("{0}'s partner tier has changed to {1}").format(doc.partner_name, doc.tier)
	return subject, f"<p>{moved}</p><p>{needed}</p><ul>{items}</ul><p>{again}</p>"
