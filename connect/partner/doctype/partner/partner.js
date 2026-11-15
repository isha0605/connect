// Copyright (c) 2026, Isha and contributors
// For license information, please see license.txt

frappe.ui.form.on("Partner", {
	refresh(frm) {
		if (frm.is_new()) return;
		add_update_revenue_button(frm);
		add_send_to_frappe_crm_button(frm);
	},
});

function add_update_revenue_button(frm) {
	// Revenue is found by the partner's email, so the button shows only once there is one.
	if (!frm.doc.email || !frm.perm[1]?.write) return;

	frm.add_custom_button(__("Update Revenue"), () =>
		frm
			.call({ method: "update_revenue", doc: frm.doc, freeze: true })
			.then(() => frm.reload_doc())
	);
}

function add_send_to_frappe_crm_button(frm) {
	// Sends go out by themselves after a save; this is for one that failed.
	if (frm.doc.frappe_crm_sync_status !== "Failed" || !frappe.user.has_role("System Manager")) return;

	frm.add_custom_button(__("Send to Frappe CRM"), () =>
		frm
			.call({ method: "send_to_frappe_crm", doc: frm.doc, freeze: true })
			.then(() => frm.reload_doc())
	);
}
