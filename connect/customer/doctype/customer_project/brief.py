# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from connect.customer.doctype.customer_project.answers import answer_label, work_label
from connect.customer.doctype.customer_project.partner_matching import get_brief_recipients
from connect.customer.doctype.customer_project.questions import get_partner_criteria

def send_to_partners(doc, customer: str) -> int:
	"""Sends the brief to each matching partner's admin, as the customer's own Requirement card
	in their thread with that partner, and returns how many got it."""
	card = requirement_card(doc, customer)
	partners = get_brief_recipients(get_partner_criteria(doc))
	for partner in partners:
		send_brief(doc, customer, partner, card)
	return len(partners)


def send_brief(doc, customer: str, partner: str, card: dict | None = None) -> str:
	"""Sends the brief to one partner, as the customer's Requirement card in their thread with
	that partner, and returns the thread."""
	from connect.messaging.doctype.connect_thread.connect_thread import get_or_open_thread

	thread = get_or_open_thread(customer, partner, doc.user)
	message = frappe.get_doc(
		{
			"doctype": "Connect Message",
			"thread": thread,
			"sender": doc.user,
			"message_type": "Requirement",
			"content": frappe.as_json(card or requirement_card(doc, customer)),
		}
	).insert(ignore_permissions=True)
	await_quote(doc.name, partner, thread, message.name)
	return thread


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
	}


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

