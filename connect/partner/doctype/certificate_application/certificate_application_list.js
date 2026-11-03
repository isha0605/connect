// Copyright (c) 2026, Isha and Contributors
// For license information, please see license.txt

frappe.listview_settings["Certificate Application"] = {
	get_indicator(doc) {
		const colors = { Applied: "orange", Approved: "blue", Certified: "green", Rejected: "red", Cancelled: "gray" };
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
