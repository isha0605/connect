// Copyright (c) 2026, Isha and contributors
// For license information, please see license.txt

const STATUS_COLORS = {
	Draft: "gray",
	Queued: "yellow",
	Running: "blue",
	Migrated: "green",
	Failed: "red",
};

frappe.listview_settings["Partner Migration"] = {
	add_fields: ["status", "is_clean"],
	get_indicator(doc) {
		// A trial run is green only when the migration may follow it.
		const color =
			doc.status === "Trial Done" ? (doc.is_clean ? "green" : "orange") : STATUS_COLORS[doc.status];
		return [__(doc.status), color || "gray", `status,=,${doc.status}`];
	},
};
