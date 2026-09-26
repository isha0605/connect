// "Tell us about your business": three steps of questions, then a hand-off to either
// Starter Packs or a partner directory filtered to the answers. The answers
// themselves are Studio variables so the form controls can v-model them; everything
// that reads or routes on them lives here.

// Grouped by the directory's regions so a country with no partners can still fall
// back to its neighbours. Names are Frappe's Country names, which is what
// Partner.country holds — e.g. "United Arab Emirates", not "UAE".
const COUNTRIES_BY_REGION = {
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

const EMPLOYEE_OPTIONS = [
	{ label: "1–10", value: "1-10" },
	{ label: "11–50", value: "11-50" },
	{ label: "51–200", value: "51-200" },
	{ label: "201–500", value: "201-500" },
	{ label: "More than 500", value: "500+" },
]

// Values are the directory's industry filter values (success-story categories), so
// the custom path can pass the answer straight through.
const MANUFACTURING_INDUSTRIES = [
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
const INDUSTRY_OPTIONS = [
	...[...MANUFACTURING_INDUSTRIES, ...OTHER_INDUSTRIES].sort().map((v) => ({ label: v, value: v })),
	{ label: "Other manufacturing", value: "Manufacturing" },
	{ label: "Other services", value: "Services" },
	{ label: "Other trading", value: "Trading and Distribution" },
	{ label: "Something else", value: "Others" },
]

const SYSTEM_OPTIONS = [
	"Tally", "Zoho Books", "QuickBooks", "Busy", "Marg", "Xero", "Odoo",
	"SAP Business One", "SAP S/4HANA", "Microsoft Dynamics", "Oracle NetSuite", "Other",
].map((v) => ({ label: v, value: v }))

// A Starter Pack is a fixed-scope setup of standard ERPNext for a small Indian
// business: GST, TDS and Indian payroll, no integrations, no customization and no
// migration off another ERP. Anything outside that is a custom implementation.
const STARTER_PACK_COUNTRY = "India"
const STARTER_PACK_TEAM_SIZES = ["1-10", "11-50"]
const CUSTOM_OPERATIONS = ["disconnected_systems", "outgrown_erp"]
const CUSTOM_PAINS = ["disconnected_systems", "tools_dont_fit"]

export default function setup(context) {
	const {
		router,
		wizardStep,
		showErrors,
		businessCountry,
		employeeCount,
		industry,
		operations,
		painPoints,
		partnerCountries,
	} = context

	const countryOptions = [
		...Object.values(COUNTRIES_BY_REGION)
			.flat()
			.sort()
			.map((v) => ({ label: v, value: v })),
		{ label: "Somewhere else", value: "Other" },
	]

	function regionOf(country) {
		return Object.keys(COUNTRIES_BY_REGION).find((r) => COUNTRIES_BY_REGION[r].includes(country))
	}

	function mapRegions(country) {
		const region = regionOf(country)
		return region ? [region] : []
	}

	function usesOtherSystems(value) {
		return !!value && value !== "spreadsheets"
	}

	function hasPain(key) {
		return (painPoints.value || []).includes(key)
	}

	function togglePain(key) {
		const current = painPoints.value || []
		painPoints.value = hasPain(key) ? current.filter((k) => k !== key) : [...current, key]
	}

	function goToStep(step) {
		showErrors.value = false
		wizardStep.value = step
	}

	function continueFromBusiness() {
		if (!businessCountry.value || !employeeCount.value || !industry.value) {
			showErrors.value = true
			return
		}
		goToStep(2)
	}

	function continueFromOperations() {
		if (!operations.value) {
			showErrors.value = true
			return
		}
		goToStep(3)
	}

	function fitsStarterPacks() {
		return (
			businessCountry.value === STARTER_PACK_COUNTRY &&
			STARTER_PACK_TEAM_SIZES.includes(employeeCount.value) &&
			!CUSTOM_OPERATIONS.includes(operations.value) &&
			!CUSTOM_PAINS.some(hasPain)
		)
	}

	function recommendedPacks() {
		const packs = ["accounts_sales_purchase_stock"]
		if (industry.value === "Manufacturing" || MANUFACTURING_INDUSTRIES.includes(industry.value)) {
			packs.push("manufacturing")
		}
		if (hasPain("hr_by_hand")) packs.push("hr", "payroll")
		return packs
	}

	// The directory's own filters, so the customer lands on a list they can see
	// and undo. A country with no partners falls back to its region, and a
	// country outside every region to no location filter at all.
	function directoryQuery() {
		const query = { category: industry.value }
		const withPartners = partnerCountries.data || []
		if (withPartners.includes(businessCountry.value)) {
			query.country = businessCountry.value
		} else if (regionOf(businessCountry.value)) {
			query.region = JSON.stringify([regionOf(businessCountry.value)])
		}
		return query
	}

	function seeRecommendation() {
		if (fitsStarterPacks()) {
			router.push({
				path: "/starter-pack-recommendation",
				query: { packs: recommendedPacks().join(",") },
			})
		} else {
			router.push({ path: "/partner-directory-redesign", query: directoryQuery() })
		}
	}

	return {
		countryOptions,
		employeeOptions: EMPLOYEE_OPTIONS,
		industryOptions: INDUSTRY_OPTIONS,
		systemOptions: SYSTEM_OPTIONS,
		mapRegions,
		usesOtherSystems,
		hasPain,
		togglePain,
		goToStep,
		continueFromBusiness,
		continueFromOperations,
		seeRecommendation,
	}
}
