// Copyright (c) 2026, Isha and Contributors
// For license information, please see license.txt

frappe.ui.form.on("Certificate Application", {
	refresh(frm) {
		if (frm.doc.status !== "Applied" || !frappe.user.has_role("Partner Reviewer")) return;

		// After approving, give the member free exam access on Frappe School; Connect can't do that part.
		frm.add_custom_button(__("Approve"), () => {
			frappe.confirm(
				__("Approve a free {0} certification for {1}? Then give them free exam access on Frappe School.", [
					frm.doc.certificate_type,
					frm.doc.member_email,
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
