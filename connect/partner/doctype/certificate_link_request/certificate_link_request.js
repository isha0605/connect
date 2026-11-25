// Copyright (c) 2026, Isha and Contributors
// For license information, please see license.txt

frappe.ui.form.on("Certificate Link Request", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status !== "Pending" || !frm.perm[0]?.write) return;

		frm.add_custom_button(__("Resend email"), () => {
			frappe.confirm(
				__("Email {0} a new approval link? The link in the earlier email stops working.", [
					frm.doc.user_email,
				]),
				() =>
					frm.call("resend").then(() => {
						frappe.show_alert({ message: __("Email sent"), indicator: "green" });
						frm.reload_doc();
					}),
			);
		});
	},
});
