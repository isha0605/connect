// Starter Pack details: what one pack includes, opened from the landing page's "What's
// included" as /starter-pack-details?pack=<key>. Every pack shares the layout and the terms;
// only the content below changes. An unknown key shows Core. The cart lives in @app/utils/starterPackCart.

import { computed } from "vue"
import { keyboardAccess } from "@app/utils/keyboard"
import { STARTER_PACK_TERMS, starterPackCart } from "@app/utils/starterPackCart"
import { startTracking } from "@app/utils/tracking"

const SETUP = {
	key: "setup",
	icon: "lucide-settings-2",
	label: "Setup",
	paragraphs: [
		{
			text: "Your site and ERPNext instance, company and print settings, chart of accounts, fiscal year and initial system configuration.",
		},
	],
}
const BUYING_SELLING = {
	key: "buying-selling",
	icon: "lucide-arrow-left-right",
	label: "Buying and selling",
	paragraphs: [
		{ text: "Material request, purchase order, purchase receipt, purchase invoice, payment" },
		{ text: "Quotation, sales order, delivery note, sales invoice, payment" },
	],
}
const STOCK = {
	key: "stock",
	icon: "lucide-warehouse",
	label: "Stock",
	paragraphs: [{ text: "Stock transfer, stock reconciliation, stock ledger, stock balance" }],
}
const ACCOUNTING = {
	key: "accounting",
	icon: "lucide-landmark",
	label: "Accounting",
	paragraphs: [
		{
			text: "Journal entry, payment reconciliation, bank reconciliation, profit and loss, balance sheet, trial balance, accounts receivable, accounts payable",
		},
	],
}
const MANUFACTURING = {
	key: "manufacturing",
	icon: "lucide-factory",
	label: "Manufacturing",
	paragraphs: [{ text: "Bill of materials, work order, stock entry, job card, stock entry" }],
}
const DATA_USERS = {
	key: "data-users",
	icon: "lucide-database",
	label: "Data and users",
	paragraphs: [
		{
			text: "How to import items, customers and addresses with Excel templates, update stock and account opening balances, and create users with basic permissions.",
		},
	],
}

const HRMS = {
	key: "hrms",
	icon: "lucide-users",
	label: "HRMS",
	paragraphs: [
		{
			text: "Employee master, leave policies, leave applications, attendance and shifts, expense claims, standard approval workflows, custom fields like skills and certifications",
		},
	],
}
const PAYROLL = {
	key: "payroll",
	icon: "lucide-wallet",
	label: "Payroll",
	paragraphs: [{ text: "Salary structures, payroll cycle, tax configuration for India, salary slips" }],
}

const ERPNEXT_LOGO = "/assets/connect/images/app_icons/erpnext.png"
const HR_LOGO = "/assets/connect/images/app_icons/frappe-hr.png"
const ERPNEXT_COVER_INTRO = "Setup first, then each module, then your data and users."

const HOW_IT_WORKS =
	"Five sessions with people who’ve done this hundreds of times. You bring your data and one owner. ERPNext is set up around how you work, and your team learns to run it."

const PACKS = {
	core: {
		logo: ERPNEXT_LOGO,
		title: "Core",
		subtitle: "For businesses that buy and sell goods or services",
		price: "₹10,000",
		hours: "5 hrs within 5 sessions",
		features: [
			{ icon: "lucide-file-text", label: "Sales and purchases tracked from first quote to payment" },
			{ icon: "lucide-arrow-right-left", label: "Bank statements matched to your ledger" },
			{ icon: "lucide-chart-line", label: "P&L and balance sheet from your own entries" },
		],
		howItWorks: HOW_IT_WORKS,
		coverIntro: ERPNEXT_COVER_INTRO,
		sections: [SETUP, BUYING_SELLING, STOCK, ACCOUNTING, DATA_USERS],
	},
	"core-manufacturing": {
		logo: ERPNEXT_LOGO,
		title: "Core + Manufacturing",
		subtitle: "For businesses that make what they sell",
		price: "₹20,000",
		hours: "10 hrs within 5 sessions",
		features: [
			{ icon: "lucide-list-tree", label: "Bills of materials for what you make" },
			{ icon: "lucide-factory", label: "Work orders and job cards, with materials and finished goods moved in stock" },
			{ icon: "lucide-layers", label: "Everything in Core" },
		],
		howItWorks: HOW_IT_WORKS,
		coverIntro: ERPNEXT_COVER_INTRO,
		sections: [SETUP, BUYING_SELLING, STOCK, ACCOUNTING, MANUFACTURING, DATA_USERS],
	},
	"hr-payroll": {
		logo: HR_LOGO,
		title: "HR and Payroll",
		subtitle: "For people, leaves and salaries on one record",
		price: "₹20,000",
		hours: "10 hrs within 5 sessions",
		features: [
			{ icon: "lucide-calendar-clock", label: "Leave, attendance and shifts tracked against your policies" },
			{ icon: "lucide-receipt-indian-rupee", label: "Salary slips every cycle, with income tax on Indian slabs" },
			{ icon: "lucide-receipt-text", label: "Expense claims submitted and approved in the system" },
		],
		howItWorks: HOW_IT_WORKS,
		coverIntro: "",
		sections: [HRMS, PAYROLL],
	},
}

export default function setup(context) {
	startTracking(context)
	const { route } = context
	keyboardAccess()

	const packKey = computed(() => (String(route.query.pack || "") in PACKS ? String(route.query.pack) : "core"))
	const pack = computed(() => PACKS[packKey.value])

	return { ...starterPackCart(context), pack, packKey, terms: STARTER_PACK_TERMS }
}
