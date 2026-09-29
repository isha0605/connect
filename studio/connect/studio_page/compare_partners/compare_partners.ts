// Compare and hire a partner: step 2 of a Starter Pack project (Figma: Frappe Connect >
// Starter pack implementation). A static mockup like the implementation checklist page —
// there's no project or quote DocType yet, so the project, its partners and their quotes
// are the literals below. When they exist, replace PROJECT and PARTNERS with resources;
// the page's {{ }} bindings read the same shapes.

import { computed } from "vue"
import { toast } from "frappe-ui"

const LOGOS = "/assets/connect/images/project"

const PROJECT = {
	title: "ERPNext implementation for Acme",
	timeline: "8-12 weeks",
	step: 2,
	steps: 4,
	stepLabel: "Compare and Hire a Partner",
	details: [
		{ label: "Service", value: "Custom implementation" },
		{ label: "Pack", value: "Manufacturing" },
		{ label: "Cost", value: "₹ 1,00,000.00" },
		{ label: "Created", value: "2 months ago" },
	],
}

// `partner` is the real Partner record, for the profile link; everything else is the mockup's.
// A partner without a quote has quote: null.
const PARTNERS = [
	{
		key: "tridots",
		partner: "Tridots Tech",
		name: "Tridots Technology",
		logo: `${LOGOS}/tridots-technology.png`,
		tier: "Gold",
		verified: false,
		location: "Chennai, India",
		quote: { amount: "$1,500", hours: "124 billed hours" },
		duration: "10-12 weeks",
		expected: "Expected mid Dec",
		list: "shortlisted",
	},
	{
		key: "greycube",
		partner: "Greycube Technologies",
		name: "Greycube",
		logo: `${LOGOS}/greycube.png`,
		tier: "",
		verified: true,
		location: "Mumbai, India",
		quote: null,
		duration: "10-12 weeks",
		expected: "Expected mid Dec",
		list: "shortlisted",
	},
	{
		key: "software-at-works",
		partner: "Software@Work",
		name: "Software@Works",
		logo: `${LOGOS}/software-at-works.png`,
		tier: "",
		verified: true,
		location: "Mumbai, India",
		quote: { amount: "$1,500", hours: "124 billed hours" },
		duration: "10-12 weeks",
		expected: "Expected mid Dec",
		list: "shortlisted",
	},
]

const RESOURCES = [
	{ key: "handbook", icon: "lucide-book-open", label: "Implementation handbook" },
	{ key: "escalation", icon: "lucide-flag", label: "Raise an escalation" },
	{ key: "contact", icon: "lucide-message-square-warning", label: "Contact Frappe" },
	{ key: "feedback", icon: "lucide-circle-help", label: "Give feedback" },
]

export default function setup(context) {
	const { router, activeTab, hiredPartner, quoteRequested } = context

	const tabs = computed(() =>
		[
			{ key: "shortlisted", label: "Shortlisted" },
			{ key: "others", label: "Others" },
		].map((t) => ({ ...t, count: PARTNERS.filter((p) => p.list === t.key).length })),
	)

	const partners = computed(() => PARTNERS.filter((p) => p.list === activeTab.value))

	// The meter: one segment per step, filled up to and including the current one.
	const steps = Array.from({ length: PROJECT.steps }, (_, i) => ({ key: i + 1, done: i < PROJECT.step }))

	function isHired(key) {
		return hiredPartner.value === key
	}

	function hire(key) {
		hiredPartner.value = isHired(key) ? "" : key
	}

	function hasRequestedQuote(key) {
		return Boolean(quoteRequested.value?.[key])
	}

	function requestQuote(row) {
		quoteRequested.value = { ...(quoteRequested.value || {}), [row.key]: true }
		toast.success(`Quote requested from ${row.name}`)
	}

	function rowMenu(row) {
		return [
			{
				label: "View profile",
				icon: "lucide-user",
				onClick: () => router.push(`/partner-profile-redesign/${encodeURIComponent(row.partner)}`),
			},
		]
	}

	function confirmPartner() {
		if (!hiredPartner.value) return
		router.push("/starter-pack-implementation")
	}

	function contactFrappe() {
		window.open("https://frappe.io/contact-us", "_blank")
	}

	function openResource(key) {
		if (key === "contact") contactFrappe()
	}

	return {
		project: PROJECT,
		resources: RESOURCES,
		steps,
		tabs,
		partners,
		isHired,
		hire,
		hasRequestedQuote,
		requestQuote,
		rowMenu,
		confirmPartner,
		contactFrappe,
		openResource,
	}
}
