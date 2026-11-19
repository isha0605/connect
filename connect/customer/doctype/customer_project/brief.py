# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from connect.customer.doctype.customer_project.answers import answer_label, work_label
from connect.customer.doctype.customer_project.partner_matching import get_brief_recipients
from connect.customer.doctype.customer_project.questions import get_partner_criteria
from connect.customer.doctype.project_quote.project_quote import QUOTED_STATUSES

def send_to_partners(doc, customer: str) -> int:
	"""Sends the brief to each matching partner's admin, as the customer's own Requirement card
	in their thread with that partner, and returns how many got it."""
	card = requirement_card(doc, customer)
	partners = get_brief_recipients(get_partner_criteria(doc))
	for partner in partners:
		send_brief(doc, customer, partner, card)
	return len(partners)




def send_requirements_update(doc, customer: str, changes: list[str]) -> int:
	"""Sends edited requirements to the partners who have them: a line saying what changed,
	then a new Requirement card. Their quotes now answer that card, and a quote made against
	the earlier version is flagged until the partner confirms it or quotes again. Returns how
	many partners got it."""
	card = {**requirement_card(doc, customer), "update": True, "changes": changes}
	line = _("Requirements updated · Changed: {0}").format(", ".join(_(change) for change in changes))
	quotes = get_update_recipients(doc.name)
	for name in quotes:
		quote = frappe.get_doc("Project Quote", name)
		frappe.get_doc("Connect Thread", quote.thread).post_system_message(line)
		quote.brief_message = _post_card(quote.thread, doc.user, card)
		quote.quoted_before_update = int(bool(quote.amount) and quote.status in QUOTED_STATUSES)
		# A system step of the customer's edit; update_requirements checked the project is theirs.
		quote.save(ignore_permissions=True)
	return len(quotes)


def get_update_recipients(project: str) -> list[str]:
	"""The briefs an edit goes to: every partner with the requirements, including those who
	declined, except partners the customer set aside (Pragati's edit-requirements spec)."""
	return frappe.get_all(
		"Project Quote",
		filters={"customer_project": project, "status": ["!=", "Not Interested"], "thread": ["is", "set"]},
		pluck="name",
	)


def send_brief(doc, customer: str, partner: str, card: dict | None = None) -> str:
	"""Sends the brief to one partner, as the customer's Requirement card in their thread with
	that partner, and returns the thread."""
	from connect.messaging.doctype.connect_thread.connect_thread import get_or_open_thread

	thread = get_or_open_thread(customer, partner, doc.user)
	await_quote(doc.name, partner, thread, _post_card(thread, doc.user, card or requirement_card(doc, customer)))
	return thread


def _post_card(thread: str, sender: str, card: dict) -> str:
	"""The customer's Requirement card in `thread`; returns the message."""
	return (
		frappe.get_doc(
			{
				"doctype": "Connect Message",
				"thread": thread,
				"sender": sender,
				"message_type": "Requirement",
				"content": frappe.as_json(card),
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def await_quote(project: str, partner: str, thread: str, brief_message: str | None = None):
	"""Remembers that this partner has the brief, so their quote can be matched to it. It is
	also the partner's lead for the brief."""
	if frappe.db.exists("Project Quote", {"customer_project": project, "partner": partner}):
		return
	frappe.get_doc(
		{
			"doctype": "Project Quote",
			"customer_project": project,
			"partner": partner,
			"thread": thread,
			"brief_message": brief_message,
		}
	).insert(ignore_permissions=True)


def requirement_card(doc, customer: str) -> dict:
	"""The Requirement card partners get: the project's answers, and its company's."""
	company = frappe.get_doc("Customer", customer)
	criteria = get_partner_criteria(doc)
	return {
		"project_name": doc.project_name,
		"company_name": company.customer_name,
		"country": company.country,
		"industry": ", ".join(company.get_industries()),
		"company_size": company.company_size,
		"apps": criteria["apps"],
		"timeline": answer_label("go_live", doc.go_live),
		"delivery_preference": work_label(criteria["work"]),
		"current_situation": _current_situation(doc),
		"budget": doc.budget,
		"description": doc.description,
		"partner_brief": partner_brief(criteria),
		# The version this card carries, as the Requirements dialog reads it.
		"rows": requirement_rows(doc, company),
	}


def requirement_rows(doc, company) -> list[dict]:
	"""The requirements as one label and value per answer, blank ones left out: what the
	Requirements dialog shows, on the project page and from each card in a chat."""
	criteria = get_partner_criteria(doc)
	place = criteria["cities"] or criteria["countries"]
	tier = _("{0} tier").format(_listed(criteria["tiers"], _("or"))) if criteria["tiers"] else _("Any tier")
	looking_for = [tier, _("in {0}").format(_listed(place, _("or"))) if place else _("anywhere"), work_label(criteria["work"]).lower()]
	systems = frappe.parse_json(doc.systems) or []
	today = [answer_label("operations", doc.operations), _("You use {0}").format(_listed(systems)) if systems else ""]
	size = answer_label("employees", company.company_size) if company else ""
	industries = company.get_industries() if company else []
	rows = [
		(_("Budget"), doc.budget),
		(_("Timeline"), answer_label("go_live", doc.go_live)),
		(_("Apps"), _listed(criteria["apps"])),
		(_("Today"), ". ".join(filter(None, today))),
		(_("To fix"), ", ".join(filter(None, (answer_label("problems", p) for p in frappe.parse_json(doc.problems) or [])))),
		(_("Looking for"), ", ".join(looking_for)),
		(_("Company"), " · ".join(filter(None, [_listed(industries), size and _("{0} employees").format(size)]))),
	]
	return [{"label": label, "text": text} for label, text in rows if text]


def _listed(values: list[str], joiner: str | None = None) -> str:
	"""The values joined as "A, B and C", or with `joiner` as "A, B or C"."""
	if len(values) <= 1:
		return "".join(values)
	return f"{', '.join(values[:-1])} {joiner or _('and')} {values[-1]}"


def partner_brief(criteria: dict) -> str:
	"""Who the brief went to, in a sentence: "A partner based in India who offers services for
	Manufacturing. Any tier, on premises or remote." """

	def either(values):
		return values[0] if len(values) == 1 else _("{0} or {1}").format(", ".join(values[:-1]), values[-1])

	place = criteria["cities"] or criteria["countries"]
	who = ""
	if place:
		who += " " + _("based in {0}").format(either(place))
	if criteria["industries"]:
		who += " " + _("who offers services for {0}").format(either(criteria["industries"]))

	tier = _("{0} tier").format(either(criteria["tiers"])) if criteria["tiers"] else _("Any tier")
	work = work_label(criteria["work"]).lower()
	# "A partner." says nothing on its own, so it's only there with a place or industry
	return (_("A partner") + who + ". " if who else "") + f"{tier}, {work}."


def _current_situation(doc) -> str:
	situation = answer_label("operations", doc.operations)
	systems = frappe.parse_json(doc.systems) or []
	problems = frappe.parse_json(doc.problems) or []

	if systems:
		situation = "; ".join(filter(None, [situation, _("uses {0}").format(", ".join(systems))]))
	if problems:
		solve = ", ".join(filter(None, (answer_label("problems", p).lower() for p in problems)))
		situation = ". ".join(filter(None, [situation, _("Wants to solve: {0}").format(solve)]))
	return situation

