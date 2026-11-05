// Copyright (c) 2026, Isha and Contributors
// For license information, please see license.txt

frappe.listview_settings["Partner Audit"] = {
	get_indicator(doc) {
		const colors = {
			Requested: "gray",
			Scheduled: "blue",
			"In Progress": "orange",
			Completed: "green",
			"On Hold": "yellow",
			Cancelled: "red",
		};
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
