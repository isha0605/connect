# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import random

import frappe
from frappe import _

from connect.customer.doctype.customer_project.customer_project import get_own_project, quote_counts
from connect.customer.doctype.project_quote.project_quote import post_quote
from connect.partner.press_integration import USD_TO_INR

# For demos, the project page has a button that makes every partner still Awaiting reply with a
# quote, posted in their thread as a Quote message the way a partner's own quote is (post_quote).
# Amounts fall within the customer's budget range, in the partner's currency; the same quote always
# gets the same numbers. The budgets are BUDGET_RANGES in recommendation.ts, each with its currency.
NOT_DECIDED = "Not decided yet"
BUDGET_RANGES = {
	"Under ₹5 lakh": ("INR", 250000, 500000),
	"₹5 to 15 lakh": ("INR", 600000, 1400000),
	"₹15 to 40 lakh": ("INR", 1600000, 3800000),
	"Over ₹40 lakh": ("INR", 4200000, 7500000),
	"Under $6k": ("USD", 3000, 6000),
	"$6k to $18k": ("USD", 7000, 17000),
	"$18k to $50k": ("USD", 19000, 46000),
	"Over $50k": ("USD", 50000, 90000),
	NOT_DECIDED: ("INR", 500000, 1200000),
}
# Demo amounts are round: to ₹12,500 or $250.
ROUND_TO = {"INR": 12500, "USD": 250}
QUOTE_NOTES = (
	"We would phase this: the core modules live first, then the parts that need integration work. "
	"The figure is for both phases.",
	"This covers setup, data migration from your current system and two weeks of support after go-live.",
	"We have done three rollouts like this in your industry. The quote includes training for your team.",
	"Fixed price for the scope in your brief. Anything beyond it we would estimate separately.",
	"Includes a discovery week up front, so the plan is agreed before any configuration starts.",
)


def simulate_quotes(name: str) -> dict:
	doc = get_own_project(name)
	if doc.status != "Shared":
		frappe.throw(_("Share the requirements first."))

	sent = 0
	# The demo answers for the partners, so these quotes must not touch any SLA clock.
	frappe.flags.simulated_answer = True
	try:
		for quote_name in frappe.get_all(
			"Project Quote", filters={"customer_project": doc.name, "status": "Awaiting"}, pluck="name"
		):
			quote = frappe.get_doc("Project Quote", quote_name)
			sender = _partner_sender(quote)
			if sender:
				_reply_with_quote(quote, sender, doc.budget)
				sent += 1
	finally:
		frappe.flags.simulated_answer = False
	return {"sent": sent, **quote_counts(doc.name)}


def _reply_with_quote(quote, sender: str, budget: str | None):
	low, high = quote_range(budget, quote.currency)
	rng = random.Random(quote.name)
	step = ROUND_TO[quote.currency]
	amount = round((low + rng.random() * (high - low)) / step) * step
	post_quote(quote, sender, amount, rng.randint(6, 10), rng.choice(QUOTE_NOTES))


def quote_range(budget: str | None, currency: str) -> tuple[float, float]:
	"""The budget's range in the quote's currency: a partner quotes in their own currency, which
	needn't be the one the customer gave their budget in."""
	budget_currency, low, high = BUDGET_RANGES.get(budget) or BUDGET_RANGES[NOT_DECIDED]
	if budget_currency == currency:
		return low, high
	rate = USD_TO_INR if currency == "INR" else 1 / USD_TO_INR
	return low * rate, high * rate


def _partner_sender(quote) -> str | None:
	"""Someone on the partner's side of the thread to send it as: an owner if one is in it."""
	from connect.permissions import _get_partner_admins

	members = frappe.get_all(
		"Connect Thread Member",
		filters={"thread": quote.thread, "side": "Partner", "is_removed": 0},
		pluck="user",
	)
	owner = next((user for user in _get_partner_admins(quote.partner) if user in members), None)
	return owner or (members[0] if members else None)
