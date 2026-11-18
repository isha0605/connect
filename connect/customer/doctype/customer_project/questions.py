# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.customer.doctype.customer_project.answers import answer_label
from connect.customer.doctype.customer_project.partner_matching import normalize_criteria

# The project questions every entry point asks, all required. Number of employees and
# industries describe the company, so they are kept on its Customer, not on the project.
TEXT_ANSWERS = ("go_live", "operations", "budget", "description")
LIST_ANSWERS = ("regions", "work_modes", "systems", "problems")
# Answers picked from answerOptions.json, which the form shows too.
OPTION_ANSWERS = {"go_live": "go_live", "operations": "operations", "problems": "problems", "work_modes": "work"}
# The one operations answer with no systems to name.
NO_SYSTEMS = "spreadsheets"

MISSING_ANSWER_MESSAGES = {
	"regions": "Pick where your partners should be from.",
	"company_size": "Pick the number of employees.",
	"industries": "Pick your industry.",
	"apps": "Pick the apps you need.",
	"go_live": "Pick when you need it live.",
	"work_modes": "Pick how you want to work.",
	"operations": "Pick how you run your operations today.",
	"systems": "Pick the systems you use.",
	"problems": "Pick what you are trying to solve.",
	"budget": "Pick a budget range.",
	"description": "Tell partners what you need.",
}


def set_answers(doc, answers: dict) -> None:
	"""Puts the form's answers on the project, and the company's on its Customer."""
	for field in TEXT_ANSWERS:
		doc.set(field, (answers.get(field) or "").strip())
	for field in LIST_ANSWERS:
		doc.set(field, frappe.as_json(_clean_list(answers.get(field))))
	if not uses_other_systems(doc.operations):
		doc.systems = frappe.as_json([])
	doc.set("apps", [{"app": app} for app in _clean_list(answers.get("apps"))])
	_check_options(doc)

	get_customer(doc).set_company_facts(
		(answers.get("company_size") or "").strip(), _clean_list(answers.get("industries"))
	)


def check_answers(doc) -> None:
	"""Stops a project from being saved or sent with any question unanswered."""
	customer = get_customer(doc)
	given = {
		**{field: doc.get(field) for field in TEXT_ANSWERS},
		**{field: frappe.parse_json(doc.get(field)) or [] for field in LIST_ANSWERS},
		"apps": doc.apps,
		"company_size": customer.company_size,
		"industries": customer.industries,
	}
	if not uses_other_systems(doc.operations):
		given.pop("systems")

	for field, message in MISSING_ANSWER_MESSAGES.items():
		if field in given and not given[field]:
			frappe.throw(_(message), title=_("Answer every question"))


def set_criteria(doc, criteria: dict) -> None:
	"""Edit criteria's picks: regions and work mode are answers, and cities and tiers are
	kept as extras. Industries and apps change only through the questions."""
	picked = normalize_criteria(criteria)
	doc.regions = frappe.as_json(picked["countries"])
	doc.work_modes = frappe.as_json(picked["work"])
	doc.criteria = frappe.as_json({"cities": picked["cities"], "tiers": picked["tiers"]})


def get_partner_criteria(doc) -> dict:
	"""Who the brief goes to, from the answers and Edit criteria's extras."""
	extras = frappe.parse_json(doc.criteria) or {}
	company = get_company(doc)
	return normalize_criteria(
		{
			"countries": frappe.parse_json(doc.regions) or [],
			"industries": company.get_industries() if company else [],
			"apps": [row.app for row in doc.apps],
			"work": frappe.parse_json(doc.work_modes) or [],
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


def _check_options(doc) -> None:
	for field, question in OPTION_ANSWERS.items():
		value = doc.get(field)
		values = frappe.parse_json(value) if field in LIST_ANSWERS else [value]
		unknown = [item for item in values or [] if item and not answer_label(question, item)]
		if unknown:
			frappe.throw(_("{0} is not one of the answers.").format(", ".join(unknown)))


def _clean_list(value) -> list[str]:
	values = frappe.parse_json(value) if isinstance(value, str) else value
	return list(dict.fromkeys(str(item).strip() for item in values or [] if str(item).strip()))
