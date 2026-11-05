// Copyright (c) 2026, Isha and Contributors
// For license information, please see license.txt

frappe.listview_settings["Partner Non Conformance"] = {
	get_indicator(doc) {
		const colors = { Open: "blue", WIP: "orange", Closed: "green", Discarded: "gray", "On Hold": "yellow" };
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
