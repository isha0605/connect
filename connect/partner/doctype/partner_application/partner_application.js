// Copyright (c) 2026, Isha and Contributors
// For license information, please see license.txt

frappe.ui.form.on("Partner Application", {
	refresh(frm) {
		const can_review = frappe.user.has_role(["Partner Manager", "System Manager"]);
		if (frm.doc.docstatus !== 1 || frm.doc.status !== "Pending Review" || !can_review) return;

		frm.add_custom_button(__("Approve"), () => {
			frappe.confirm(
				__("Approve {0}? The partner becomes Verified, and this application's logo and state go to their profile.", [
					frm.doc.company_name || frm.doc.partner,
				]),
				() => frm.call("approve").then(() => frm.reload_doc()),
			);
		});
		frm.add_custom_button(__("Reject"), () => {
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Why? The partner sees this."), reqd: 1 },
				({ reason }) => frm.call("reject", { reason }).then(() => frm.reload_doc()),
				__("Reject application"),
				__("Reject"),
			);
		});
	},
});
