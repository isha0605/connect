// Copyright (c) 2026, Isha and contributors
// For license information, please see license.txt

frappe.ui.form.on("Customer", {
	refresh(frm) {
		if (frm.is_new() || !frappe.user.has_role("System Manager")) return;
		const label = frm.doc.frappe_crm_sync_status === "Failed" ? __("Send to Frappe CRM again") : __("Send to Frappe CRM");
		frm.add_custom_button(label, () =>
			frappe
				.call({
					method: "connect.crm_partner_leads.send_to_frappe_crm",
					args: { customer: frm.doc.name },
					freeze: true,
				})
				.then(() => {
					frappe.show_alert({ message: __("Sending to Frappe CRM"), indicator: "blue" });
					frm.reload_doc();
				}),
		);
	},
});
