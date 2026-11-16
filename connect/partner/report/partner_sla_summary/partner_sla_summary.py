# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import Case
from frappe.query_builder.functions import Coalesce, Sum
from frappe.utils import add_to_date, getdate

# Fewer scored answers than this shows "New": one brief is no basis for 0% or 100%.
MIN_SCORED_ANSWERS = 3
CLOCKS = ("brief", "hire", "chat")
# Where each clock lives: its doctype, then per clock its status field, when it was
# answered, and its deadline.
QUOTE_CLOCKS = {
	"brief": ("sla_status", "answered_on", "response_by"),
	"hire": ("hire_sla_status", "responded_on", "hire_response_by"),
}
CHAT_CLOCKS = {"chat": ("status", "replied_at", "reply_by")}


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict]]:
	"""Each partner's answer SLA: on-time and late counts per clock, and a score of
	on time ÷ (on time + late). Timely declines and running clocks count in neither."""
	filters = _validate_filters(filters)
	per_clock = {
		**_get_clock_counts("Project Quote", QUOTE_CLOCKS, filters),
		**_get_clock_counts("Partner Chat Reply", CHAT_CLOCKS, filters),
	}
	partners = {partner for counts in per_clock.values() for partner in counts}
	rows = [_make_row(partner, per_clock) for partner in partners]
	# Lowest scores first, so the partners needing attention lead; New partners last.
	return get_columns(), sorted(rows, key=lambda row: (row["is_new"], row["sla_score"] or 0, row["partner"]))


def get_columns() -> list[dict]:
	labels = {
		"brief": (_("Requirements: On Time"), _("Requirements: Late")),
		"hire": (_("Hire Requests: On Time"), _("Hire Requests: Late")),
		"chat": (_("Chat Replies: On Time"), _("Chat Replies: Late")),
	}
	columns = [
		{"label": _("Partner"), "fieldname": "partner", "fieldtype": "Link", "options": "Partner", "width": 220},
	]
	for clock in CLOCKS:
		on_time_label, late_label = labels[clock]
		columns += [
			{"label": on_time_label, "fieldname": f"{clock}_on_time", "fieldtype": "Int", "width": 130},
			{"label": late_label, "fieldname": f"{clock}_late", "fieldtype": "Int", "width": 110},
		]
	return columns + [
		{"label": _("Total On Time"), "fieldname": "total_on_time", "fieldtype": "Int", "width": 120},
		{"label": _("Total Late"), "fieldname": "total_late", "fieldtype": "Int", "width": 100},
		{"label": _("SLA Score"), "fieldname": "sla_score", "fieldtype": "Percent", "width": 110},
	]


def _validate_filters(filters) -> frappe._dict:
	filters = frappe._dict(filters or {})
	if not filters.from_date or not filters.to_date:
		frappe.throw(_("Pick a from date and a to date."))
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("The from date must be on or before the to date."))
	return filters


def _make_row(partner: str, per_clock: dict) -> dict:
	row = {"partner": partner}
	for clock in CLOCKS:
		on_time, late = per_clock[clock].get(partner, (0, 0))
		row[f"{clock}_on_time"], row[f"{clock}_late"] = on_time, late

	row["total_on_time"] = sum(row[f"{clock}_on_time"] for clock in CLOCKS)
	row["total_late"] = sum(row[f"{clock}_late"] for clock in CLOCKS)
	scored = row["total_on_time"] + row["total_late"]
	row["is_new"] = scored < MIN_SCORED_ANSWERS
	row["sla_score"] = None if row["is_new"] else round(row["total_on_time"] / scored * 100, 1)
	return row


def _get_clock_counts(doctype: str, clocks: dict, filters) -> dict:
	"""(on time, late) per partner for each of a doctype's clocks, in one pass over it."""
	Table = frappe.qb.DocType(doctype)
	start, end = getdate(filters.from_date), add_to_date(getdate(filters.to_date), days=1)

	sums, scored = [], None
	for clock, (status_field, answered_field, deadline_field) in clocks.items():
		status = Table[status_field]
		dated_on = _dated_on(status, Table[answered_field], Table[deadline_field])
		in_period = (dated_on >= start) & (dated_on < end)
		sums += [
			Sum(Case().when((status == "Fulfilled") & in_period, 1).else_(0)).as_(f"{clock}_on_time"),
			Sum(Case().when((status == "Failed") & in_period, 1).else_(0)).as_(f"{clock}_late"),
		]
		is_scored = status.isin(("Fulfilled", "Failed"))
		scored = is_scored if scored is None else scored | is_scored

	query = frappe.qb.from_(Table).select(Table.partner, *sums).where(scored).groupby(Table.partner)
	if filters.partner:
		query = query.where(Table.partner == filters.partner)

	counts = {clock: {} for clock in clocks}
	for row in query.run(as_dict=True):
		for clock in clocks:
			if row[f"{clock}_on_time"] or row[f"{clock}_late"]:
				counts[clock][row.partner] = (int(row[f"{clock}_on_time"]), int(row[f"{clock}_late"]))
	return counts


def _dated_on(status, answered_on, deadline):
	"""A miss belongs to its deadline, so a late answer arriving afterwards cannot move it
	into another period. An on-time answer belongs to when it was given."""
	return Case().when(status == "Failed", deadline).else_(Coalesce(answered_on, deadline))
