import frappe
from frappe.utils import now_datetime

from connect.partner.sla import get_answer_deadline


def execute():
	"""Briefs and hire requests already waiting when the SLA shipped get a clock that starts
	now, not retroactively, so nobody fails for time before the rules existed."""
	_start_clocks("Awaiting", "response_by", "sla_status")
	_start_clocks("Hire Requested", "hire_response_by", "hire_sla_status")


def _start_clocks(status: str, deadline_field: str, status_field: str):
	deadlines = {}
	rows = frappe.get_all(
		"Project Quote", filters={"status": status, status_field: ["is", "not set"]}, fields=["name", "partner"]
	)

	for row in rows:
		if row.partner not in deadlines:
			deadlines[row.partner] = get_answer_deadline(row.partner, now_datetime())
		if not deadlines[row.partner]:
			continue

		frappe.db.set_value(
			"Project Quote",
			row.name,
			{deadline_field: deadlines[row.partner], status_field: "Due"},
			update_modified=False,
		)
