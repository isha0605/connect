// Copyright (c) 2026, Isha and Contributors
// For license information, please see license.txt

frappe.listview_settings["Partner"] = {
	add_fields: ["enabled", "verification_status"],

	get_indicator(doc) {
		if (!doc.enabled) {
			return [__("Disabled"), "gray", "enabled,=,0"];
		}

		const colors = {
			"Pending Review": "orange",
			Verified: "green",
			Rejected: "red",
		};
		const status = doc.verification_status;
		return [__(status), colors[status] || "gray", `verification_status,=,${status}`];
	},
};
