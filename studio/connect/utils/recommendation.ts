// What "Tell us about your business" asks, and what the answers mean: Starter Packs
// (and which ones) or a custom implementation. Shared by the questionnaire, which
// routes on it, and the Starter Pack recommendation page, which explains it — so the
// two can never disagree about why someone was sent where they were.

// Grouped by the directory's regions so a country with no partners can still fall
// back to its neighbours. Names are Frappe's Country names, which is what
// Partner.country holds — e.g. "United Arab Emirates", not "UAE".
export const COUNTRIES_BY_REGION = {
	India: ["India"],
	Asia: [
		"Australia", "Bangladesh", "China", "Indonesia", "Myanmar", "Pakistan",
		"Philippines", "Singapore", "Sri Lanka", "Thailand", "Vietnam",
	],
	"Middle East": [
		"Bahrain", "Egypt", "Iraq", "Jordan", "Kuwait", "Libya", "Oman", "Qatar",
		"Saudi Arabia", "United Arab Emirates", "Yemen",
	],
	Africa: [
		"Congo - Kinshasa", "Ghana", "Kenya", "Mauritius", "Nigeria", "South Africa",
		"Tanzania", "Uganda",
	],
	Europe: [
		"France", "Germany", "Italy", "Malta", "Netherlands", "Spain", "Switzerland",
		"United Kingdom",
	],
	Americas: ["Canada", "United States"],
}

export const COUNTRY_OPTIONS = [
	...Object.values(COUNTRIES_BY_REGION)
		.flat()
		.sort()
		.map((v) => ({ label: v, value: v })),
	{ label: "Somewhere else", value: "Other" },
]

export const EMPLOYEE_OPTIONS = [
	{ label: "1 to 10", value: "1-10" },
	{ label: "11 to 50", value: "11-50" },
	{ label: "51 to 200", value: "51-200" },
	{ label: "201 to 500", value: "201-500" },
	{ label: "More than 500", value: "500+" },
]

// Values are the directory's industry filter values (success-story categories), so
// the custom path can pass the answer straight through.
export const MANUFACTURING_INDUSTRIES = [
	"Automotive Manufacturing", "Chemical Manufacturing", "Discrete Manufacturing",
	"Electronics Manufacturing", "Food and Beverages", "Furniture Manufacturing",
	"Jewellery Manufacturing", "Medical Device Manufacturing",
	"Pharmaceutical Manufacturing", "Process Manufacturing", "Steel Manufacturing",
	"Textile Manufacturing",
]
const OTHER_INDUSTRIES = [
	"Agriculture", "Aviation Industry", "Distribution", "E-commerce", "Education",
	"Engineering and Construction", "Fast Moving Consumer Goods", "Finance",
	"Government", "Hospitality", "Logistics", "Nonprofit", "Professional services",
	"Real Estate", "Rental Business", "Retail",
]
export const INDUSTRY_OPTIONS = [
	...[...MANUFACTURING_INDUSTRIES, ...OTHER_INDUSTRIES].sort().map((v) => ({ label: v, value: v })),
	{ label: "Other manufacturing", value: "Manufacturing" },
	{ label: "Other services", value: "Services" },
	{ label: "Other trading", value: "Trading and Distribution" },
	{ label: "Something else", value: "Others" },
]

export const OPERATION_OPTIONS = [
	{ value: "spreadsheets", label: "Spreadsheets, email and paper" },
	{ value: "accounting_software", label: "Accounting software, everything else by hand" },
	{ value: "disconnected_systems", label: "Several systems that do not talk to each other" },
	{ value: "outgrown_erp", label: "An ERP that no longer fits how we work" },
]

export const SYSTEM_OPTIONS = [
	"Tally", "Zoho", "QuickBooks", "Busy", "SAP", "Microsoft Dynamics", "Odoo",
	"Salesforce", "An in-house system", "Something else",
].map((v) => ({ label: v, value: v }))

export const PROBLEM_OPTIONS = [
	{ value: "manual_work", label: "Manual work that should be automated" },
	{ value: "hr_by_hand", label: "Payroll, leave and attendance are run by hand" },
	{ value: "disconnected_systems", label: "Systems that do not talk to each other" },
	{ value: "slow_close", label: "Month-end close and reporting take too long" },
	{ value: "stock_visibility", label: "No reliable view of stock and orders" },
	{ value: "tools_dont_fit", label: "Our tools cannot handle how we actually work" },
	{ value: "outgrowing", label: "We are outgrowing what we have" },
]

const labelOf = (options, value) => options.find((o) => o.value === value)?.label ?? ""

export function regionOf(country) {
	return Object.keys(COUNTRIES_BY_REGION).find((r) => COUNTRIES_BY_REGION[r].includes(country))
}

// A Starter Pack is a fixed-scope setup of ERPNext exactly as it ships, for under 50
// users. Each of these rules one out; the reason is shown to the customer as-is.
// The India rule is ours, not the prototype's: packs are only priced in INR today,
// and they configure GST, TDS and Indian payroll.
const CUSTOM_TRIGGERS = [
	{
		test: (a) => !!a.country && a.country !== "India",
		reason: () => "Starter Packs are set up for Indian businesses today — GST, TDS and Indian payroll.",
	},
	{
		test: (a) => ["51-200", "201-500", "500+"].includes(a.employees),
		reason: (a) => `You're ${labelOf(EMPLOYEE_OPTIONS, a.employees)} people, and a pack is scoped for under 50 users.`,
	},
	{
		test: (a) => a.operations === "outgrown_erp",
		reason: () => "You are already on an ERP, so this is a migration — a pack is a fresh configuration.",
	},
	{
		test: (a) => a.problems.includes("tools_dont_fit"),
		reason: () => "You need the software to bend to how you work, and a pack is ERPNext exactly as it ships.",
	},
]

// Why the core pack helps, keyed by the first problem it answers.
const CORE_PACK_REASONS = {
	manual_work: "Stops the same order being typed into three places",
	disconnected_systems: "One system for orders, invoices and stock, instead of three",
	slow_close: "Month-end closes off the ledger your orders already write to",
	stock_visibility: "Stock that moves when an order does",
	outgrowing: "The base the rest of ERPNext is built on",
}

// Pack key -> why it's recommended for these answers, or null when it isn't.
const PACK_REASONS = {
	accounts_sales_purchase_stock: (a) => {
		// Only payroll and leave to fix: HR and Payroll cover it on their own.
		if (a.problems.length === 1 && a.problems[0] === "hr_by_hand") return null
		const first = a.problems.find((p) => CORE_PACK_REASONS[p])
		return first ? CORE_PACK_REASONS[first] : "The base the rest of ERPNext is built on"
	},
	manufacturing: (a) =>
		a.industry === "Manufacturing" || MANUFACTURING_INDUSTRIES.includes(a.industry)
			? `You're in ${a.industry.toLowerCase()}, so work orders and BOMs get planned against the stock you hold`
			: null,
	hr: (a) =>
		a.problems.includes("hr_by_hand")
			? "Leave and attendance are kept by hand today; this puts them on one employee record"
			: null,
	payroll: (a) =>
		a.problems.includes("hr_by_hand")
			? "Salaries are worked out by hand today; this runs them off the attendance HR records"
			: null,
}

function normalize(answers) {
	return {
		country: answers?.country ?? "",
		employees: answers?.employees ?? "",
		industry: answers?.industry ?? "",
		operations: answers?.operations ?? "",
		systems: answers?.systems ?? [],
		problems: answers?.problems ?? [],
	}
}

// { verdict: "packs" | "custom", reasons: [...], packs: [{ key, reason }] }
export function recommend(answers) {
	const a = normalize(answers)
	const packs = Object.keys(PACK_REASONS)
		.map((key) => ({ key, reason: PACK_REASONS[key](a) }))
		.filter((p) => p.reason)
	const triggers = CUSTOM_TRIGGERS.filter((t) => t.test(a))
	if (triggers.length) {
		return { verdict: "custom", reasons: triggers.map((t) => t.reason(a)), packs }
	}
	return {
		verdict: "packs",
		reasons: [
			`You're ${labelOf(EMPLOYEE_OPTIONS, a.employees)} people with no ERP to migrate off, so a fixed scope fits without anyone scoping it first.`,
			a.operations
				? `Today it's ${labelOf(OPERATION_OPTIONS, a.operations).toLowerCase()} — which is what these packs replace.`
				: null,
		].filter(Boolean),
		packs,
	}
}

// Answers travel in the URL, so the recommendation survives a reload and "Change my
// answers" can hand them back to the questionnaire.
export function answersToQuery(answers) {
	const a = normalize(answers)
	const query = {
		country: a.country,
		employees: a.employees,
		industry: a.industry,
		operations: a.operations,
		systems: a.systems.join(","),
		problems: a.problems.join(","),
	}
	return Object.fromEntries(Object.entries(query).filter(([, v]) => v))
}

export function answersFromQuery(query) {
	if (!query?.employees) return null
	const list = (v) => (v ? String(v).split(",").filter(Boolean) : [])
	return normalize({
		country: query.country,
		employees: query.employees,
		industry: query.industry,
		operations: query.operations,
		systems: list(query.systems),
		problems: list(query.problems),
	})
}

export const OUR_NEEDS = [
	"Keep strictly to the scope",
	"Nominate a project champion",
	"Have your data ready",
	"Approve internally without delay",
	"Make your users available for training",
]

export const EXTRA_HOUR_RATE = 2000

// The commercial terms, shared by the recommendation page (before paying) and the
// confirmed page (after paying) so the two never say something different.
export function commercialTerms(gstRate, money) {
	return [
		"Payment to Frappe in full, in advance",
		`${gstRate}% GST charged on top`,
		`Extra hours beyond the pack: ${money(EXTRA_HOUR_RATE)} per hour, plus ${gstRate}% GST`,
		"Scope is limited to what the pack lists. Anything else is a change request, and more hours",
		"Validity runs from the project start date",
		"For businesses running fewer than 50 users",
		"Your Frappe Cloud subscription is billed separately",
		`Product warranty applies on Frappe Cloud plans above ${money(4100)} + GST a month`,
	]
}

// The partner directory's own filters, so the customer lands on a list they can see
// and undo. A country with no listed partners falls back to its region, and a country
// outside every region to no location filter at all.
export function directoryQuery(answers, countriesWithPartners = []) {
	const a = normalize(answers)
	const query = {}
	if (a.industry) query.category = a.industry
	if (countriesWithPartners.includes(a.country)) {
		query.country = a.country
	} else if (regionOf(a.country)) {
		query.region = JSON.stringify([regionOf(a.country)])
	}
	return query
}
