# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import random

import frappe
from frappe import _

from connect.customer.doctype.customer_project.customer_project import get_own_project, quote_counts

# Partners have no way to send a quote yet, so the project page has a button that makes
# every partner still Awaiting reply with one, posted in their thread as a Quote message.
# Amounts fall within the customer's budget range; the same quote always gets the same numbers.
BUDGET_RANGES = {
	"Under ₹5 lakh": (250000, 500000),
	"₹5 to 15 lakh": (600000, 1400000),
	"₹15 to 40 lakh": (1600000, 3800000),
	"Over ₹40 lakh": (4200000, 7500000),
	"Not decided yet": (500000, 1200000),
}
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

	budget_range = BUDGET_RANGES.get(doc.budget, BUDGET_RANGES["Not decided yet"])
	sent = 0
	for quote_name in frappe.get_all(
		"Project Quote", filters={"customer_project": doc.name, "status": "Awaiting"}, pluck="name"
	):
		quote = frappe.get_doc("Project Quote", quote_name)
		sender = _partner_sender(quote)
		if sender:
			_reply_with_quote(quote, doc.name, sender, budget_range)
			sent += 1
	return {"sent": sent, **quote_counts(doc.name)}


def _reply_with_quote(quote, project: str, sender: str, budget_range: tuple[int, int]):
	low, high = budget_range
	rng = random.Random(quote.name)
	quote.amount = round((low + rng.random() * (high - low)) / 12500) * 12500
	quote.timeline_weeks = rng.randint(6, 10)
	quote.note = rng.choice(QUOTE_NOTES)

	message = frappe.get_doc(
		{
			"doctype": "Connect Message",
			"thread": quote.thread,
			"sender": sender,
			"message_type": "Quote",
			"content": frappe.as_json(
				{
					"quote": quote.name,
					"project": project,
					"amount": quote.amount,
					"weeks": quote.timeline_weeks,
					"note": quote.note,
				}
			),
		}
	).insert(ignore_permissions=True)

	quote.quote_message = message.name
	quote.status = "Quoted"
	quote.quoted_on = frappe.utils.now_datetime()
	quote.save(ignore_permissions=True)


def _partner_sender(quote) -> str | None:
	"""Someone on the partner's side of the thread to send it as: their admin if they're in it."""
	from connect.permissions import _get_partner_admin

	admin = _get_partner_admin(quote.partner)
	members = frappe.get_all(
		"Connect Thread Member",
		filters={"thread": quote.thread, "side": "Partner", "is_removed": 0},
		pluck="user",
	)
	return admin if admin in members else (members[0] if members else None)
