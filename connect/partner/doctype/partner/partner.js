// Copyright (c) 2026, Isha and contributors
// For license information, please see license.txt

frappe.ui.form.on("Partner", {
	refresh(frm) {
		// Revenue is found by the partner's email, so the button shows only once there is one.
		if (frm.is_new() || !frm.doc.email || !frm.perm[1]?.write) return;

		frm.add_custom_button(__("Update Revenue"), () =>
			frm
				.call({ method: "update_revenue", doc: frm.doc, freeze: true })
				.then(() => frm.reload_doc())
		);
	},
});
