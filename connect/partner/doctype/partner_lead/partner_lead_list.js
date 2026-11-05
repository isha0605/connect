// Copyright (c) 2026, Isha and contributors
// For license information, please see license.txt

const STAGE_COLORS = { Won: "green", Lost: "red", Junk: "gray", Closed: "gray" };

frappe.listview_settings["Partner Lead"] = {
	add_fields: ["stage"],
	get_indicator(doc) {
		return [__(doc.stage), STAGE_COLORS[doc.stage] || "blue", `stage,=,${doc.stage}`];
	},
};
