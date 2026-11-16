// Copyright (c) 2026, Isha and contributors
// For license information, please see license.txt

frappe.ui.form.on("Review Request", {
	refresh(frm) {
		// The partner sends and answers these from Connect; Desk shows where each one stands.
		frm.disable_form();
		if (frm.doc.status === "Declined") {
			frm.set_intro(__("The contact said they didn't work with this partner. Check before trusting the partner's other reviews."), "red");
		} else if (frm.doc.is_free_email) {
			frm.set_intro(__("The contact's email is on a free provider, so it says less about where they work."), "orange");
		}
	},
});
