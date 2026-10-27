# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from connect.customer.doctype.customer_project.answers import answer_label, work_label
from connect.customer.doctype.customer_project.partner_matching import get_partner_filters, normalize_criteria

def send_to_partners(doc, customer: str) -> int:
	"""Sends the brief to each matching partner's admin, as the customer's own Requirement card
	in their thread with that partner, and returns how many got it."""
	card = requirement_card(doc, customer)
	partners = _partners_to_brief(normalize_criteria(frappe.parse_json(doc.criteria) or {}))
	for partner in partners:
		send_brief(doc, customer, partner, card)
	return len(partners)


def send_brief(doc, customer: str, partner: str, card: dict | None = None) -> str:
	"""Sends the brief to one partner, as the customer's Requirement card in their thread with
	that partner, and returns the thread."""
	from connect.messaging.doctype.connect_thread.connect_thread import get_or_open_thread

	thread = get_or_open_thread(customer, partner, doc.user)
	frappe.get_doc(
		{
			"doctype": "Connect Message",
			"thread": thread,
			"sender": doc.user,
			"message_type": "Requirement",
			"content": frappe.as_json(card or requirement_card(doc, customer)),
		}
	).insert(ignore_permissions=True)
	await_quote(doc.name, partner, thread)
	return thread


def await_quote(project: str, partner: str, thread: str):
	"""Remembers that this partner has the brief, so their quote can be matched to it."""
	if frappe.db.exists("Project Quote", {"customer_project": project, "partner": partner}):
		return
	frappe.get_doc(
		{"doctype": "Project Quote", "customer_project": project, "partner": partner, "thread": thread}
	).insert(ignore_permissions=True)


def requirement_card(doc, customer: str) -> dict:
	"""The same Requirement card a customer sends from Messaging: their saved requirement and
	company, with this project's name, brief and answers on top."""
	from connect.customer.doctype.requirement.requirement import get_requirement_snapshot

	company = frappe.db.get_value("Customer", customer, ["customer_name", "industry", "country"], as_dict=True) or {}
	criteria = normalize_criteria(frappe.parse_json(doc.criteria) or {})
	industries = frappe.parse_json(doc.industries) or []

	card = get_requirement_snapshot(customer) or {}
	card.update(
		{
			"project_name": doc.project_name,
			"company_name": card.get("company_name") or company.get("customer_name"),
			# what they picked themselves, before anything saved for the company
			"industry": ", ".join(industries) or card.get("industry") or company.get("industry"),
			"country": card.get("country") or company.get("country"),
			"company_size": doc.company_size or card.get("company_size"),
			"description": doc.description,
			"looking_for": looking_for(doc),
			"current_situation": _current_situation(doc) or card.get("current_situation"),
			"timeline": answer_label("go_live", doc.go_live) or card.get("timeline"),
			"delivery_preference": work_label(criteria["work"]) if criteria["work"] else card.get("delivery_preference"),
			"budget": doc.budget,
			"partner_brief": partner_brief(criteria),
		}
	)
	return card


def looking_for(doc) -> str:
	# A project sent from a partner's Connect button has no brief written yet: its name says it.
	if not doc.description:
		return doc.project_name
	return _("Custom implementation: {0}").format(doc.description)


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


def _partners_to_brief(criteria: dict) -> list[str]:
	"""Matching partners that have an admin to read the brief."""
	with_admin = frappe.get_all("Connect Partner Member", filters={"is_admin": 1}, pluck="partner", distinct=True)
	filters = [*get_partner_filters(criteria), ["Partner", "name", "in", with_admin or [""]]]
	return frappe.get_all("Partner", filters=filters, pluck="name")


def _current_situation(doc) -> str:
	situation = answer_label("operations", doc.operations)
	systems = frappe.parse_json(doc.systems) or []
	problems = frappe.parse_json(doc.problems) or []

	if systems:
		situation = "; ".join(filter(None, [situation, _("uses {0}").format(", ".join(systems))]))
	if problems:
		fix = ", ".join(filter(None, (answer_label("problems", p).lower() for p in problems)))
		situation = ". ".join(filter(None, [situation, _("Wants fixed: {0}").format(fix)]))
	return situation

