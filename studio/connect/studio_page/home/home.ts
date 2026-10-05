import { computed } from "vue"
import { call, toast } from "frappe-ui"

// Home for a signed-in buyer: their Starter Pack projects and saved partners come from the
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

// The directory's tier seal, so a saved partner looks the same here as in Find Partners.
const SEAL_PATH =
	"M13.4912 0.226893C13.7636 -0.0756311 14.236 -0.0756311 14.509 0.226893L16.4868 2.42128C16.6752 2.62965 16.969 2.70274 17.2316 2.60614L19.9959 1.58885C20.3773 1.44859 20.7952 1.66961 20.8973 2.06512L21.6363 4.9339C21.7064 5.20632 21.9337 5.40882 22.2102 5.44612L25.1275 5.83898C25.5298 5.89314 25.7981 6.28454 25.706 6.68242L25.0359 9.56839C24.9727 9.84243 25.08 10.128 25.3083 10.2906L27.7098 12.0036C28.0408 12.2398 28.0982 12.7119 27.8327 13.021L25.9077 15.263C25.7251 15.4759 25.6886 15.7791 25.8155 16.0298L27.1516 18.6705C27.3354 19.0347 27.1678 19.4793 26.7905 19.6288L24.0511 20.7133C23.7914 20.8162 23.6193 21.0676 23.6158 21.349L23.5798 24.3125C23.5752 24.721 23.2216 25.0364 22.8182 24.992L19.8922 24.6705C19.6145 24.64 19.3461 24.7819 19.2134 25.0295L17.8141 27.6368C17.6211 27.9963 17.1626 28.1101 16.8259 27.8821L14.3833 26.2282C14.1514 26.0711 13.8482 26.0711 13.6164 26.2282L11.1744 27.8821C10.8376 28.1101 10.3791 27.9963 10.1861 27.6368L8.78682 25.0295C8.65408 24.7819 8.38512 24.64 8.10748 24.6705L5.18144 24.992C4.77859 25.0364 4.42501 24.721 4.4198 24.3125L4.38444 21.349C4.38096 21.0676 4.2088 20.8162 3.94855 20.7133L1.20916 19.6288C0.831813 19.4793 0.664291 19.0347 0.848617 18.6705L2.1847 16.0298C2.31164 15.7791 2.27512 15.4759 2.09195 15.263L0.167536 13.021C-0.0979398 12.7119 -0.0411269 12.2398 0.289849 12.0036L2.69188 10.2906C2.91968 10.128 3.02749 9.84243 2.96373 9.56839L2.29425 6.68242C2.2015 6.28454 2.46987 5.89314 2.87214 5.83898L5.78948 5.44612C6.06655 5.40882 6.2932 5.20632 6.36333 4.9339L7.10237 2.06512C7.20439 1.66961 7.62232 1.44859 8.00372 1.58885L10.768 2.60614C11.0306 2.70274 11.3251 2.62965 11.5129 2.42128L13.4912 0.226893Z"
const TICK_PATH =
	"M18.0202 9.62684C18.324 9.27238 18.8561 9.23364 19.2079 9.53963C19.5603 9.84586 19.5992 10.3815 19.2955 10.7361L13.0521 18.015C12.8945 18.1993 12.6649 18.3066 12.4232 18.3092C12.1815 18.3116 11.9502 18.2091 11.7885 18.0282L8.83117 14.7193C8.52048 14.3711 8.54773 13.835 8.8932 13.5217C9.23925 13.2084 9.77193 13.2365 10.0832 13.5844L12.4012 16.1779L18.0202 9.62684Z"
const SEAL_COLORS = { Gold: "#D4A017", Silver: "#A6A6A6", Bronze: "#7A4A28" }

export default function setup(context) {
	const { router, myProfile, myProjects, myShortlist } = context

	// ---- Greeting ----
	const greeting = computed(() => {
		const hour = new Date().getHours()
		const part = hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening"
		const firstName = String(myProfile.data?.full_name || "").trim().split(/\s+/)[0]
		return firstName ? `Good ${part}, ${firstName}` : `Good ${part}`
	})

	// ---- Projects ----
	const projects = computed(() => myProjects.data || [])
	const projectsSummary = computed(() => {
		const active = projects.value.filter((p) => p.is_active).length
		if (!active) return "No active projects yet"
		return `You have ${active} active project${active === 1 ? "" : "s"}`
	})

	const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" })
	// get_my_projects sends ISO datetimes with the site's offset, so this is right in any zone.
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
		router.push({ path: "/starter-pack-implementation", query: { order: project.order } })
	}

	function newProject() {
		router.push("/starter-packs-redesign")
	}

	// ---- Saved partners ----
	const savedPartners = computed(() => (myShortlist.data || []).slice(0, 3))

	function partnerLocation(p) {
		return [p.city, p.country].filter(Boolean).join(", ")
	}

	// In rupees, as the partner directory shows it.
	function partnerRate(p) {
		return p.hourly_rate ? `From ₹${Number(p.hourly_rate).toLocaleString("en-IN")}/hr` : "Undisclosed"
	}

	function partnerRating(p) {
		return p.rating ? Number(p.rating).toFixed(1) : "New"
	}

	function partnerResponse(p) {
		return p.response_time_hours ? `Typically ${p.response_time_hours}h` : "Response time unknown"
	}

	// Gold gets a badge with the seal; Silver and Bronze get the seal on its own.
	function tierSeal(tier, size) {
		const fill = SEAL_COLORS[tier] || SEAL_COLORS.Silver
		return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 28 28" fill="none"><path d="${SEAL_PATH}" fill="${fill}"></path><path d="${TICK_PATH}" fill="white"></path></svg>`
	}

	function openPartner(p) {
		router.push(`/partner-profile-redesign/${encodeURIComponent(p.name)}`)
	}

	function unsavePartner(p) {
		call("connect.api.customer.remove_from_shortlist", { partner: p.name })
			.then(() => myShortlist.reload())
			.catch(() => toast.error("Couldn't remove this partner. Try again."))
	}

	function viewSaved() {
		router.push("/shortlisted-redesign")
	}

	// ---- Frappe's content ----
	function openLink(url) {
		window.open(url, "_blank", "noopener")
	}

	// ---- Rail: logo account menu (same as the implementation page) ----
	function accountMenuOptions() {
		return [
			{
				icon: "lucide-log-out",
				label: "Log out",
				onClick: () => {
					call("logout").then(() => {
						window.location.href = "/login"
					})
				},
			},
		]
	}

	return {
		greeting,
		projects,
		projectsSummary,
		timeAgo,
		openProject,
		newProject,
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
		accountMenuOptions,
	}
}
