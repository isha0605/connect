// Copyright (c) 2026, Isha and contributors
// For license information, please see license.txt

frappe.ui.form.on("Partner CRM Settings", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.enabled || !frappe.user.has_role("System Manager")) return;

		// New chats reach the CRM by themselves; this brings over the ones from before sync was on.
		frm.add_custom_button(__("Send all chats to CRM"), () => {
			frappe.confirm(
				__("Send every chat with {0} to their CRM, including older ones?", [frm.doc.partner]),
				() =>
					frappe
						.call("connect.crm_integration.send_all_chats", { partner: frm.doc.partner })
						.then((r) =>
							frappe.show_alert({
								message: __("{0} chats queued for the CRM", [r.message]),
								indicator: "green",
							})
						)
			);
		});

		frm.add_custom_button(__("Set up CRM webhooks again"), () =>
			frappe
				.call("connect.crm_integration.reset_reply_webhook", { partner: frm.doc.partner })
				.then(() => {
					frappe.show_alert({ message: __("CRM webhooks set up"), indicator: "green" });
					frm.reload_doc();
				})
		);

		// Links each team member to their CRM user by email, for Lead owners on both sides.
		frm.add_custom_button(__("Match team with CRM"), () =>
			frappe
				.call("connect.crm_lead_owner.match_crm_team", { partner: frm.doc.partner })
				.then((r) =>
					frappe.show_alert({
						message: __("{0} of the team are on the CRM", [r.message]),
						indicator: "green",
					})
				)
		);
	},
});
