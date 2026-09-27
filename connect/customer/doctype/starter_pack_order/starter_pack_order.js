// Copyright (c) 2026
// For license information, please see license.txt

frappe.ui.form.on("Starter Pack Order", {
	refresh(frm) {
		// Runs the same round robin that assigns partners on payment, for an order that was
		// paid while no partner was available. Setting the Partner field directly still
		// works too, and doesn't move the rotation.
		if (frm.doc.payment_status === "Paid" && !frm.doc.partner && frappe.user.has_role("System Manager")) {
			frm.add_custom_button(__("Assign partner"), () => {
				frappe.call({
					method: "connect.customer.doctype.starter_pack_order.partner_rotation.assign_now",
					args: { order: frm.doc.name },
					freeze: true,
					callback: () => frm.reload_doc(),
				});
			});
		}
	},
});
