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
					method: "connect.starter_packs.doctype.starter_pack_order.implementation.assign_now",
					args: { order: frm.doc.name },
					freeze: true,
					callback: () => frm.reload_doc(),
				});
			});
		}

		// A paid order placed without a company (before checkout asked for one) has no chat or
		// company details until it's linked to one.
		if (frappe.user.has_role("System Manager") && frm.doc.payment_status === "Paid" && !frm.doc.customer) {
			frm.add_custom_button(__("Link to a company"), () => {
				frappe.prompt(
					{ fieldname: "customer", fieldtype: "Link", options: "Customer", label: __("Company"), reqd: 1 },
					({ customer }) => {
						frappe.call({
							method: "connect.starter_packs.doctype.starter_pack_order.implementation.link_company",
							args: { order: frm.doc.name, customer },
							freeze: true,
							callback: () => frm.reload_doc(),
						});
					},
					__("Link to a company"),
					__("Link"),
				);
			});
		}
	},
});
