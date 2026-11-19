# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import json
from functools import cache
from pathlib import Path

import frappe
from frappe import _


def answer_label(question: str, value: str | None) -> str:
	"""The translated wording of a questionnaire answer, or "" when there's none."""
	label = _answer_labels(question).get(value)
	return _(label) if label else ""


@cache
def _answer_labels(question: str) -> dict[str, str]:
	"""The questionnaire's options, from the file the frontend imports too, so the customer
	and partners see the same words."""
	path = Path(frappe.get_app_path("connect")).parent / "studio/connect/utils/answerOptions.json"
	options = json.loads(path.read_text())
	return {option["value"]: option["label"] for option in options[question]}
