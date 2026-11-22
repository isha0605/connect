// Copyright (c) 2026, Isha and contributors
// For license information, please see license.txt

frappe.ui.form.on("Partner Review", {
	refresh(frm) {
		if (frm.is_new() || !(frappe.user.has_role("Partner Manager") || frappe.user.has_role("System Manager"))) return;

		if (frm.doc.is_hidden) {
			frm.add_custom_button(__("Show review"), () => {
				frappe.confirm(__("Show this review on the partner's profile and count it in their rating again?"), () =>
					frm.call("show").then(() => frm.reload_doc()),
				);
			});
			return;
		}
		frm.add_custom_button(__("Hide review"), () => {
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Why? Kept on the review for Frappe's team."), reqd: 1 },
				({ reason }) => frm.call("hide", { reason }).then(() => frm.reload_doc()),
				__("Hide review"),
				__("Hide"),
			);
		});
	},
});
