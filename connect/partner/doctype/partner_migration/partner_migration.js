// Copyright (c) 2026, Isha and contributors
// For license information, please see license.txt

frappe.ui.form.on("Partner Migration", {
	refresh(frm) {
		if (frm.is_new()) return;
		const { status, last_step, is_clean, is_checked, crm_queued_on } = frm.doc;

		if (["Draft", "Trial Done", "Failed"].includes(status)) {
			frm.add_custom_button(__("Trial Run"), () => start(frm, "start_trial_run"));
		}
		if (status === "Trial Done" && is_clean) {
			frm.add_custom_button(__("Run Migration"), () =>
				frappe.confirm(
					__("This reads the sources again, saves their partner data into Connect and copies their files. Continue?"),
					() => start(frm, "start_migration"),
				),
			);
		}
		if (status === "Migrated") {
			frm.add_custom_button(__("Check"), () => start(frm, "start_check"));
		}
		if (status === "Migrated") {
			// The migration copies the files; this tries again the ones it couldn't.
			frm.add_custom_button(__("Copy Files"), () => start(frm, "start_copy_files"));
		}
		if (status === "Migrated" && is_checked && !crm_queued_on) {
			frm.add_custom_button(__("Send to Frappe CRM"), () =>
				frappe.confirm(
					__("Send every approved partner to Frappe CRM?"),
					() => start(frm, "send_to_frappe_crm"),
				),
			);
		}

		if (["Queued", "Running"].includes(status)) {
			frm.dashboard.set_headline(
				__("{0} is running. This page updates when it finishes.", [__(last_step)]),
			);
			frm.add_custom_button(__("Mark as Failed"), () =>
				frappe.confirm(
					__("Do this only when the step is stuck and its job has stopped. Mark it as failed?"),
					() => start(frm, "mark_as_failed"),
				),
			);
		}
	},
});

function start(frm, method) {
	frm.call(method).then(() => frm.reload_doc());
}
