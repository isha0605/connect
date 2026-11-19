# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.customer.doctype.customer_project.answers import answer_label
from connect.customer.doctype.customer_project.partner_matching import normalize_criteria

# The project questions every entry point asks. Where the company is based, its size and its
# industries describe the company, so they are kept on its Customer, not on the project.
TEXT_ANSWERS = ("operations", "other_system", "budget", "description")
LIST_ANSWERS = ("systems", "problems")
COMPANY_FACTS = ("country", "company_size", "industries")
# Answers picked from answerOptions.json, which the form shows too.
OPTION_ANSWERS = {"operations": "operations", "problems": "problems"}
# The one operations answer with no systems to name, and the system that asks for its name.
NO_SYSTEMS = "spreadsheets"
OTHER_SYSTEM = "Something else"

# The required questions. How they run today (operations, systems, what else) is optional.
MISSING_ANSWER_MESSAGES = {
	"country": "Pick where your business is based.",
	"company_size": "Pick the number of employees.",
	"industries": "Pick your industry.",
	"problems": "Pick what you are trying to fix.",
	"budget": "Pick a budget range.",
	"apps": "Pick the apps you need.",
	"description": "Tell partners what you need.",
}


# What an edit names as changed, in the short nouns partners read in the thread.
CHANGE_NAMES = {
	"description": "description",
	"budget": "budget",
	"apps": "apps",
	"operations": "today",
	"systems": "today",
	"other_system": "today",
	"problems": "to fix",
	"criteria": "looking for",
}


def set_answers(doc, answers: dict) -> None:
	"""Puts the given answers on the project, and the company's on its Customer. A question
	left out keeps its answer, so a project that lacks a few can be given just those."""
	for field in TEXT_ANSWERS:
		if field in answers:
			doc.set(field, (answers[field] or "").strip())
	for field in LIST_ANSWERS:
		if field in answers:
			doc.set(field, frappe.as_json(_clean_list(answers[field])))
	if "apps" in answers:
		doc.set("apps", [{"app": app} for app in _clean_list(answers["apps"])])
	if "criteria" in answers:
		# Edit criteria's extras: partner cities and tiers.
		extras = normalize_criteria(answers["criteria"])
		doc.criteria = frappe.as_json({"cities": extras["cities"], "tiers": extras["tiers"]})
	if not uses_other_systems(doc.operations):
		doc.systems = frappe.as_json([])
	if OTHER_SYSTEM not in (frappe.parse_json(doc.systems) or []):
		doc.other_system = ""
	check_options(doc)
	customer = get_customer(doc)
	facts = {field: answers[field] for field in COMPANY_FACTS if field in answers}
	if "industries" in facts:
		facts["industries"] = _clean_list(facts["industries"])
	customer.set_company_facts(facts)


# Get started's Contact partners wizard doesn't ask what they want fixed or the apps.
NOT_ASKED_BY_CONTACT_PARTNERS = ("problems", "apps")


def check_answers(doc, not_asked: tuple[str, ...] = ()) -> None:
	"""Stops a project from being saved or sent with any question unanswered, other than those
	its entry point doesn't ask (`not_asked`)."""
	given = {
		**{field: doc.get(field) for field in TEXT_ANSWERS},
		**{field: frappe.parse_json(doc.get(field)) or [] for field in LIST_ANSWERS},
		"apps": doc.apps,
		**get_customer(doc).get_company_facts(),
	}
	for field, message in MISSING_ANSWER_MESSAGES.items():
		if field not in not_asked and not given[field]:
			frappe.throw(_(message), title=_("Answer every question"))


def get_answers(doc) -> dict:
	"""The project's own answers, in a form two versions can be compared in."""
	extras = frappe.parse_json(doc.criteria) or {}
	return {
		**{field: doc.get(field) or "" for field in TEXT_ANSWERS},
		**{field: sorted(frappe.parse_json(doc.get(field)) or []) for field in LIST_ANSWERS},
		"apps": sorted(row.app for row in doc.apps),
		"criteria": {group: sorted(extras.get(group) or []) for group in ("cities", "tiers")},
	}


def get_changes(before: dict, after: dict) -> list[str]:
	"""What changed between two versions of the answers, each named once."""
	return list(dict.fromkeys(name for field, name in CHANGE_NAMES.items() if before.get(field) != after.get(field)))


def get_partner_criteria(doc) -> dict:
	"""Who the brief goes to: partners with the apps and the company's industries, in the
	company's country when partners are there and anywhere otherwise, and Edit criteria's extras."""
	extras = frappe.parse_json(doc.criteria) or {}
	company = get_company(doc)
	country = company.country if company else ""
	return normalize_criteria(
		{
			"countries": [country] if country and _has_partners_in(country) else [],
			"industries": company.get_industries() if company else [],
			"apps": [row.app for row in doc.apps],
			"cities": extras.get("cities"),
			"tiers": extras.get("tiers"),
		}
	)


def get_customer(doc):
	"""The project owner's company, which answers its own questions."""
	company = get_company(doc)
	if not company:
		frappe.throw(_("Sign in with your company account to describe your project."), frappe.PermissionError)
	return company


def get_company(doc):
	"""The project owner's company, or None for a project made in the Desk or by someone who
	has since left it."""
	customer = get_customer_for_user(doc.user or frappe.session.user)
	return frappe.get_doc("Customer", customer) if customer else None


def uses_other_systems(operations: str | None) -> bool:
	return bool(operations) and operations != NO_SYSTEMS


def check_options(doc) -> None:
	"""Stops an answer that isn't one of the form's options, such as an operations of "tomorrow"."""
	for field, question in OPTION_ANSWERS.items():
		value = doc.get(field)
		values = frappe.parse_json(value) if field in LIST_ANSWERS else [value]
		unknown = [item for item in values or [] if item and not answer_label(question, item)]
		if unknown:
			frappe.throw(_("{0} is not one of the answers.").format(", ".join(unknown)))


def _has_partners_in(country: str) -> bool:
	from connect.partner.doctype.partner.partner import BASE_PARTNER_FILTERS

	return bool(frappe.get_all("Partner", filters=[*BASE_PARTNER_FILTERS, ["Partner", "country", "=", country]], limit=1))


def _clean_list(value) -> list[str]:
	values = frappe.parse_json(value) if isinstance(value, str) else value
	return list(dict.fromkeys(str(item).strip() for item in values or [] if str(item).strip()))
