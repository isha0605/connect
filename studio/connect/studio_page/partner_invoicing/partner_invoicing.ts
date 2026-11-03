// The partner's Invoicing: their Frappe Cloud bill for a month, which covers the customers whose
// Frappe Cloud accounts they pay for and their own, less their tier discount. Clicking an invoice
// opens its line items beside the list. Sample data for now: Frappe Cloud doesn't yet give Connect
// a partner's monthly invoices. openInvoice is a page variable, so the editor can show the panel.

import { computed, ref, watch } from "vue"
import { startTracking } from "@app/utils/tracking"

const BILLING_URL = "https://frappecloud.com/dashboard/billing"
const NOT_YET = "Not available yet. Invoices will come from Frappe Cloud."

// month -> the bill; the newest month is still accruing
const SAMPLE_BILLS = {
	"2026-10": {
		status: "Accruing",
		tierDiscount: 20,
		invoices: [
			invoice("INV-26100447", "Kestrel", "arjun@kestrel.example", [
				["kestrel.frappe.cloud", "Business", 72000],
				["kestrel-hr.frappe.cloud", "Standard", 24350],
			]),
			invoice("INV-26100558", "Meridian", "vikram@meridian.example", [["meridian.frappe.cloud", "Business", 38900]]),
			invoice("INV-26100632", "Silverpine", "neha@silverpine.example", [["silverpine.frappe.cloud", "Business", 24480]]),
			invoice("INV-26100706", "Your account", "accounts@softwarework.example", [["softwarework-demo.frappe.cloud", "Starter", 8260]], true),
		],
	},
	"2026-09": {
		status: "Paid",
		tierDiscount: 20,
		invoices: [
			invoice("INV-26090412", "Kestrel", "arjun@kestrel.example", [
				["kestrel.frappe.cloud", "Business", 72000],
				["kestrel-hr.frappe.cloud", "Standard", 22100],
			]),
			invoice("INV-26090519", "Meridian", "vikram@meridian.example", [["meridian.frappe.cloud", "Business", 36200]]),
			invoice("INV-26090601", "Silverpine", "neha@silverpine.example", [["silverpine.frappe.cloud", "Business", 22900]]),
			invoice("INV-26090688", "Your account", "accounts@softwarework.example", [["softwarework-demo.frappe.cloud", "Starter", 8260]], true),
		],
	},
	"2026-08": {
		status: "Paid",
		tierDiscount: 15,
		invoices: [
			invoice("INV-26080390", "Kestrel", "arjun@kestrel.example", [["kestrel.frappe.cloud", "Business", 90500]]),
			invoice("INV-26080477", "Meridian", "vikram@meridian.example", [["meridian.frappe.cloud", "Business", 35000]]),
			invoice("INV-26080560", "Your account", "accounts@softwarework.example", [["softwarework-demo.frappe.cloud", "Starter", 7900]], true),
		],
	},
}
const STATUS_THEMES = { Accruing: "gray", Paid: "green", Unpaid: "red" }

function invoice(name, customer, email, items, own = false) {
	const lines = items.map(([site, plan, amount]) => ({ site, plan, amount }))
	return { name, customer, email, own, items: lines, amount: lines.reduce((sum, line) => sum + line.amount, 0) }
}

const rupees = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })
const monthName = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric" })

// The first letter or digit, so "_Acme" or "@Work" still shows a letter.
function initialOf(name) {
	return (String(name).match(/[\p{L}\p{N}]/u) || ["?"])[0].toUpperCase()
}

function monthLabel(month) {
	return monthName.format(new Date(`${month}-01T00:00:00`))
}

export default function setup(context) {
	startTracking(context)
	const { toast, openInvoice, myContext } = context

	const months = Object.keys(SAMPLE_BILLS).sort().reverse()
	const month = ref(months[0])
	const bill = computed(() => SAMPLE_BILLS[month.value] || { invoices: [], tierDiscount: 0, status: "" })
	watch(month, () => (openInvoice.value = ""))

	// ---- Totals ----
	const subtotal = computed(() => bill.value.invoices.reduce((sum, row) => sum + row.amount, 0))
	const discount = computed(() => Math.round((subtotal.value * bill.value.tierDiscount) / 100))

	// ---- The list, largest first unless the partner flips it ----
	// The partner's own bill shows as "Your account", with their company's initial.
	const ownName = computed(() => myContext?.data?.partner?.partner_name || "Your account")
	const descending = ref(true)
	const rows = computed(() =>
		[...bill.value.invoices]
			.sort((a, b) => (descending.value ? b.amount - a.amount : a.amount - b.amount))
			.map((row) => ({
				...row,
				initial: initialOf(row.own ? ownName.value : row.customer),
				amountText: rupees.format(row.amount),
				active: row.name === openInvoice.value,
			})),
	)

	// ---- One invoice beside the list ----
	const selected = computed(() => bill.value.invoices.find((row) => row.name === openInvoice.value) || null)

	return {
		breadcrumbItems: [{ label: "Invoices", route: "/partner-invoicing" }],
		openBilling: () => window.open(BILLING_URL, "_blank", "noopener"),
		month,
		monthOptions: months.map((value) => ({ label: monthLabel(value), value })),
		menuOptions: [
			{ label: "Download all invoices", icon: "lucide-download", onClick: () => toast.info(NOT_YET) },
			{ label: "Email this month's statement", icon: "lucide-mail", onClick: () => toast.info(NOT_YET) },
		],
		subtotalText: computed(() => rupees.format(subtotal.value)),
		discountLabel: computed(() => `Tier discount, ${bill.value.tierDiscount}%`),
		discountText: computed(() => `−${rupees.format(discount.value)}`),
		totalText: computed(() => rupees.format(subtotal.value - discount.value)),
		billStatus: computed(() => bill.value.status),
		billTheme: computed(() => STATUS_THEMES[bill.value.status] || "gray"),
		rows,
		hasRows: computed(() => rows.value.length > 0),
		emptyText: computed(() => `No invoices for ${monthLabel(month.value)}.`),
		descending,
		sortIcon: computed(() => (descending.value ? "lucide-arrow-down" : "lucide-arrow-up")),
		toggleSort: () => (descending.value = !descending.value),
		showInvoice: (row) => (openInvoice.value = row.name === openInvoice.value ? "" : row.name),
		closeInvoice: () => (openInvoice.value = ""),
		selected,
		selectedTitle: computed(() => selected.value?.customer || ""),
		selectedMeta: computed(() => (selected.value ? `${selected.value.name} · ${monthLabel(month.value)}` : "")),
		selectedLines: computed(() => (selected.value?.items || []).map((line) => ({ ...line, amountText: rupees.format(line.amount) }))),
		selectedTotal: computed(() => (selected.value ? rupees.format(selected.value.amount) : "")),
		downloadInvoice: () => toast.info(NOT_YET),
		emailInvoice: () => toast.info(NOT_YET),
	}
}
