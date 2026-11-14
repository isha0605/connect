// Copyright (c) 2026, Isha and contributors
// For license information, please see license.txt

frappe.query_reports["Partner SLA Summary"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -89),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "partner",
			label: __("Partner"),
			fieldtype: "Link",
			options: "Partner",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		// Too few answers for a fair score: say so instead of a misleading 0% or 100%.
		if (column.fieldname === "sla_score" && data && data.is_new) {
			return `<span class="text-muted">${__("New")}</span>`;
		}
		return default_formatter(value, row, column, data);
	},
};
