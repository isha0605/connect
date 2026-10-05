// Copyright (c) 2026
// For license information, please see license.txt

frappe.ui.form.on("Starter Pack Order", {
	refresh(frm) {
		// Hands the order over the same way payment does (the Implemented By partner, or the
		// round robin when it's on), for an order paid while no partner was available. Setting
		// the Partner field directly still works too, and doesn't move the rotation.
		if (frm.doc.payment_status === "Paid" && !frm.doc.partner && frappe.user.has_role("System Manager")) {
			frm.add_custom_button(__("Assign partner"), () => {
				frappe.call({
					method: "connect.customer.doctype.starter_pack_order.implementation.assign_now",
					args: { order: frm.doc.name },
					freeze: true,
					callback: () => frm.reload_doc(),
				});
			});
		}
	},
});
