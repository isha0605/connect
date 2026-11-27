import { computed, watch } from "vue"
import { call, toast } from "frappe-ui"
import { hourlyRate, viewerCurrency } from "@app/utils/money"
import { projectDialog, projectPath } from "@app/utils/projectDialog"
import { startTracking } from "@app/utils/tracking"
import { useMyContext } from "@app/utils/myContext"
import { tierSeal } from "@app/utils/tierSeal"

// Home for a signed-in buyer: their latest projects and saved partners come from the
// server; Resources, Blog and Upcoming events are Frappe's own content, kept here as literals
// until there's a source to read them from. The {{ }} bindings read the same shapes.

const RESOURCES = [
	{
		key: "hiring-guide",
		date: "23 Aug 2026",
		title: "Your guide to finding and hiring the perfect Partner for your company",
		url: "https://frappe.io/partners",
	},
	{
		key: "working-with-partners",
		date: "23 Aug 2026",
		title: "How to work effectively with Partners to get your app implementation just right",
		url: "https://frappe.io/partners",
	},
]

const FEATURED_POST = {
	title: "What a fixed-scope implementation can and cannot do for you",
	excerpt:
		"Where a Starter Pack stops, what a change request costs, and how to tell which one your project needs before you book.",
	author: "Frappe",
	category: "Starter Packs",
	url: "https://frappe.io/blog",
}

const POSTS = [
	{
		key: "off-spreadsheets",
		title: "Off spreadsheets in 90 days: a manufacturer’s first quarter on ERPNext",
		excerpt: "Stock, job cards and the month-end close, one at a time",
		author: "Frappe",
		category: "Customer stories",
		likes: 41,
		comments: 6,
		url: "https://frappe.io/blog",
	},
	{
		key: "certifying-partners",
		title: "Why we started certifying Frappe Partners",
		excerpt: "What the Gold badge means, and what it takes to earn one",
		author: "Frappe",
		category: "Partners",
		likes: 19,
		comments: 1,
		url: "https://frappe.io/blog",
	},
]

const EVENTS = [
	{
		key: "partnership",
		month: "Sep",
		day: "30",
		title: "Frappe Partnership",
		where: "Online",
		time: "3:00 PM IST",
		url: "https://frappe.io/events",
	},
	{
		key: "karavan",
		month: "Nov",
		day: "21",
		title: "Frappe Karavan",
		where: "Cairo, Riyadh, Doha, Dubai",
		time: "10:00 AM EET",
		url: "https://frappe.io/events",
	},
]

// Home shows the newest few; the Projects page lists them all.
const HOME_PROJECTS = 6

// Home is the buyer's start page. A partner's team member who lands here (the app's own
// address, or a link back to Home) goes to their own start: Leads, Customers or onboarding.
function sendPartnersHome(router) {
	if (window.location.pathname.startsWith("/studio/")) return
	const myContext = useMyContext()
	watch(
		() => myContext.data,
		(data) => {
			if (data?.partner) router.replace(data.partner.home_route || "/partner-listing")
		},
		{ immediate: true },
	)
}

export default function setup(context) {
	startTracking(context)
	const { router, myProfile, projectList, myShortlist } = context
	const myContext = useMyContext()
	sendPartnersHome(router)

	// ---- Greeting ----
	const greeting = computed(() => {
		const hour = new Date().getHours()
		const part = hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening"
		const firstName = String(myProfile.data?.full_name || "").trim().split(/\s+/)[0]
		return firstName ? `Good ${part}, ${firstName}` : `Good ${part}`
	})

	// ---- Projects ----
	// The Projects page's list (draft projects and paid Starter Packs, newest first), as cards.
	const allProjects = computed(() => projectList?.data || [])
	const projects = computed(() =>
		allProjects.value.slice(0, HOME_PROJECTS).map((row) => ({
			...row,
			key: row.order || row.project,
			title: row.project_title,
			partner: { company_name: row.company_name, logo: row.partner_logo },
		})),
	)
	const hasMoreProjects = computed(() => allProjects.value.length > HOME_PROJECTS)
	const projectsSummary = computed(() => {
		const active = allProjects.value.filter((p) => p.status !== "Completed").length
		if (!active) return "No active projects yet"
		return `You have ${active} active project${active === 1 ? "" : "s"}`
	})

	const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" })
	// list_projects sends ISO datetimes with the site's offset, so this is right in any zone.
	function timeAgo(value) {
		if (!value) return ""
		const days = Math.round((new Date(value).getTime() - Date.now()) / 86400000)
		if (days > -1) return "Today"
		if (days > -7) return relative.format(days, "day")
		if (days > -30) return relative.format(Math.round(days / 7), "week")
		if (days > -365) return relative.format(Math.round(days / 30), "month")
		return relative.format(Math.round(days / 365), "year")
	}

	function openProject(project) {
		router.push(projectPath(project))
	}

	// New project: shared with every matching partner, then opens on its quotes.
	const dialog = projectDialog()

	function viewAllProjects() {
		router.push("/projects")
	}

	// ---- Saved partners ----
	const savedPartners = computed(() => (myShortlist.data || []).slice(0, 3))

	function partnerLocation(p) {
		return [p.city, p.country].filter(Boolean).join(", ")
	}

	// In the partner's currency, as the partner directory shows it.
	function partnerRate(p) {
		return p.hourly_rate ? hourlyRate(p.hourly_rate, p.currency, viewerCurrency(myContext.data)) : "Undisclosed"
	}

	function partnerRating(p) {
		return p.rating ? Number(p.rating).toFixed(1) : "New"
	}

	function partnerResponse(p) {
		return p.response_time_hours ? `Typically ${p.response_time_hours}h` : "Response time unknown"
	}

	function openPartner(p) {
		router.push(`/partner-profile/${encodeURIComponent(p.name)}`)
	}

	function unsavePartner(p) {
		call("connect.api.customer.remove_from_shortlist", { partner: p.name })
			.then(() => myShortlist.reload())
			.catch(() => toast.error("Couldn't remove this partner. Try again."))
	}

	function viewSaved() {
		router.push("/saved-partners")
	}

	// ---- Frappe's content ----
	function openLink(url) {
		window.open(url, "_blank", "noopener")
	}


	return {
		myContext,
		...dialog,
		greeting,
		projects,
		hasMoreProjects,
		projectsSummary,
		timeAgo,
		openProject,
		viewAllProjects,
		savedPartners,
		partnerLocation,
		partnerRate,
		partnerRating,
		partnerResponse,
		tierSeal,
		openPartner,
		unsavePartner,
		viewSaved,
		resources: RESOURCES,
		featuredPost: FEATURED_POST,
		posts: POSTS,
		events: EVENTS,
		openLink,
	}
}
