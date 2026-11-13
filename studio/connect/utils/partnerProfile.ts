// A partner's own profile as the Profile builder and the Listing page edit it: the editable
// copy ("draft") of connect.api.partner.get_my_profile, the limits update_my_partner_profile
// enforces, and the payload that saves it.

import { useFileUpload } from "frappe-ui"

export const PROFILE_API = "connect.api.partner"
export const MAX_INDUSTRIES = 6
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024
// The gallery's limits, as connect.partner.doctype.partner.partner checks them on save.
export const MAX_GALLERY_PHOTOS = 6
export const MAX_GALLERY_VIDEOS = 2
// Frappe's own upload limit (System Settings leaves it at the default).
export const MAX_VIDEO_BYTES = 25 * 1024 * 1024
const DRAFT_FIELDS = [
	"tagline",
	"website",
	"phone",
	"journey_blog_url",
	"logo",
	"logo_icon",
	"description",
	"year_founded",
	"team_size",
	"address",
	"city",
	"country",
	"hourly_rate",
	"why_choose_them",
	"how_we_work",
	"successful_implementation",
	"origin_story",
]

// What the editor shows when its user is on no partner's team, such as Administrator.
export const SAMPLE_PROFILE = {
	partner: "Sample Partner",
	partner_name: "Sample Partner",
	tagline: "ERPNext implementations for manufacturers",
	website: "https://www.example.com",
	phone: "+91 98400 00000",
	description: "Sample Partner builds custom ERPNext solutions for businesses of all sizes.",
	year_founded: 2015,
	team_size: "51-200",
	certs_erpnext: 8,
	certs_frappe_framework: 3,
	address: "No. 100, Lake View Estate, Main Road\nChennai, Tamil Nadu 600116, India",
	city: "Chennai",
	country: "India",
	hourly_rate: 2500,
	why_choose_them: "We aim for excellence in every line of code and every customer conversation.",
	how_we_work: "A dedicated team, a weekly demo and one shared plan from kickoff to go-live.",
	successful_implementation: "Your team runs its month-end close on ERPNext without calling us.",
	apps: ["ERPNext", "Frappe HR"],
	migrations: ["Tally to ERPNext"],
	founder: { member_name: "Asha Rao", designation: "Founder and CEO", bio: "Twenty years in manufacturing IT." },
	photos: [],
	success_stories: [{ client_name: "Refex", headline: "Refex runs its plants on ERPNext", category: "Manufacturing" }],
	industries: ["Manufacturing", "Textile Manufacturing"],
	industry_badges: [
		{ industry: "Manufacturing", stories: 3, verified: true },
		{ industry: "Textile Manufacturing", stories: 1, verified: false },
	],
	suggested_industries: [{ industry: "Agriculture", stories: 2 }],
	tier: "Gold",
	pmm_level: 3,
	is_verified: true,
	can_edit: true,
	has_unpublished_changes: true,
	options: { apps: ["ERPNext", "Frappe HR"], countries: ["India", "United States"], migrations: ["Tally to ERPNext"], industries: ["Agriculture", "Manufacturing", "Retail", "Textile Manufacturing"], categories: ["Manufacturing"] },
}

// The same limits update_my_partner_profile enforces, with the label and builder tab to point at.
export const LIMITS = {
	tagline: { limit: 80, label: "Tagline", tab: "basics" },
	description: { limit: 500, label: "Introduction", tab: "about" },
	address: { limit: 200, label: "Address", tab: "about" },
	why_choose_them: { limit: 300, label: "Why work with us and who should work with us", tab: "vision" },
	how_we_work: { limit: 300, label: "How we'll work together", tab: "vision" },
	successful_implementation: { limit: 300, label: "Successful implementation", tab: "vision" },
	"founder.member_name": { limit: 60, label: "Founder name", tab: "founder" },
	"founder.designation": { limit: 40, label: "Founder role", tab: "founder" },
	"founder.bio": { limit: 280, label: "Founder bio", tab: "founder" },
	origin_story: { limit: 400, label: "How we got here", tab: "story" },
}
export const STORY_LIMITS = { client_name: 40, headline: 90 }

// What the public profile shows for a vision answer the partner hasn't written.
export const DEFAULT_ANSWERS = {
	why_choose_them: "We aim for excellence in every line of code, every UI interaction, and every customer conversation.",
	how_we_work:
		"Transparency, honesty, and trust form the core of our work ethic. We believe in doing the right thing even when no one is watching. We have dedicated teams working with you to ensure quality, focus, and accountability.",
	successful_implementation:
		"Good is never enough. We aim for excellence in every line of code, every UI interaction, and every customer conversation. With 15+ years of experience, we understand that implementation doesn't end at handoff, but is built via on-ground involvement through strategy, setup, and execution, with visible results in 6-8 months. We train your team so improvements stay in place long after we've left.",
}

// "founder.bio" → draft.founder.bio
export function valueAt(source, path) {
	return path.split(".").reduce((value, key) => value?.[key], source)
}

export function isBlank(value) {
	return Array.isArray(value) ? value.length === 0 : !String(value ?? "").trim() || value === 0
}

export function toOptions(values) {
	return (values || []).map((value) => ({ label: value, value }))
}

export function toDraft(data) {
	// whole-number fields store 0 when unset; a blank box reads better than "0"
	const fields = Object.fromEntries(DRAFT_FIELDS.map((field) => [field, data[field] || ""]))
	return {
		...fields,
		apps: [...(data.apps || [])],
		migrations: [...(data.migrations || [])],
		industries: [...(data.industries || [])],
		delivery_options: [...(data.delivery_options || [])],
		founder: { member_name: "", designation: "", bio: "", photo: "", ...(data.founder || {}) },
		photos: (data.photos || []).map((photo) => ({ ...photo })),
		success_stories: (data.success_stories || []).map((story) => ({ ...story })),
	}
}

// "12 over" or "68/80": counted, never cut, so pasted text is kept for the partner to trim.
export function limitCounter(draft, path) {
	const { limit } = LIMITS[path]
	const used = String(valueAt(draft, path) ?? "").length
	return used > limit ? `${used - limit} over` : `${used}/${limit}`
}

export function isOverLimit(draft, path) {
	return String(valueAt(draft, path) ?? "").length > LIMITS[path].limit
}

export function storyCounter(story, field) {
	const used = String(story[field] || "").length
	return used > STORY_LIMITS[field] ? `${used - STORY_LIMITS[field]} over` : `${used} / ${STORY_LIMITS[field]}`
}

export function isStoryOver(story, field) {
	return String(story[field] || "").length > STORY_LIMITS[field]
}

// ---- Client logos: one row of them, from the success stories ----

// Fewer logos than this make a sparse row, so the profile leaves it out.
export const MIN_CLIENT_LOGOS = 4
const CLIENT_LOGOS_SHOWN = 6
// Each logo covers about the same area, so a tall mark isn't dwarfed by a wide wordmark. Heavy
// artwork (more of it inked, measured by connect.partner.logo) gets a little less, light artwork
// a little more, so no logo looks louder than the rest.
const LOGO_AREA = 2600
const TYPICAL_INK = 0.3
const LOGO_MAX = { width: 130, height: 40 }
// A logo not measured yet (still being cleaned) fits this box, as all logos did before.
const UNMEASURED_LOGO = { width: "100px", height: "28px" }

export function clientLogoCount(stories) {
	return (stories || []).filter((story) => story.client_logo).length
}

// The row's logos with their sizes, or none when there are too few for a row.
export function clientLogoRow(stories) {
	if (clientLogoCount(stories) < MIN_CLIENT_LOGOS) return []
	return stories
		.filter((story) => story.client_logo)
		.slice(0, CLIENT_LOGOS_SHOWN)
		.map((story) => ({ ...story, logo: story.client_logo_display || story.client_logo, ...clientLogoSize(story) }))
}

function clientLogoSize(story) {
	const ratio = Number(story.client_logo_ratio)
	if (!ratio) return UNMEASURED_LOGO

	const ink = Number(story.client_logo_ink) || TYPICAL_INK
	const area = LOGO_AREA * Math.min(1.25, Math.max(0.8, Math.sqrt(TYPICAL_INK / ink)))
	let width = Math.sqrt(area * ratio)
	let height = Math.sqrt(area / ratio)
	if (height > LOGO_MAX.height) [height, width] = [LOGO_MAX.height, LOGO_MAX.height * ratio]
	if (width > LOGO_MAX.width) [width, height] = [LOGO_MAX.width, LOGO_MAX.width / ratio]
	return { width: `${Math.round(width)}px`, height: `${Math.round(height)}px` }
}

// Why the draft can't be saved yet, or "". Only text changed since `saved` must fit its limit, as on
// the server: text saved before the limits existed doesn't block the rest of the profile.
export function overLimitPaths(draft, saved) {
	return Object.keys(LIMITS).filter((path) => isOverLimit(draft, path) && valueAt(draft, path) !== valueAt(saved, path))
}

export function draftProblem(draft, saved) {
	const over = overLimitPaths(draft, saved)[0]
	if (over) return `Shorten ${LIMITS[over].label} to ${LIMITS[over].limit} characters before saving.`
	const year = String(draft.year_founded || "").trim()
	if (year && !/^\d{4}$/.test(year)) return "Enter the year founded as four digits, like 2015."
	if (Number(draft.hourly_rate) < 0) return "Hourly rate can't be negative."
	if ((draft.industries || []).length > MAX_INDUSTRIES) return `Pick up to ${MAX_INDUSTRIES} industries.`
	return ""
}

export function toSavePayload(draft) {
	const { apps, migrations, industries, delivery_options, founder, photos, success_stories, ...fields } = draft
	return {
		...fields,
		// number fields: an empty box saves as 0, which the profile shows as unset
		year_founded: String(fields.year_founded || "").trim() || 0,
		hourly_rate: fields.hourly_rate || 0,
		apps: JSON.stringify(apps),
		migrations: JSON.stringify(migrations),
		industries: JSON.stringify(industries || []),
		delivery_options: JSON.stringify(delivery_options || []),
		founder: JSON.stringify(founder),
		photos: JSON.stringify(photos),
		success_stories: JSON.stringify(success_stories),
	}
}

export function imageTile(url) {
	return url ? `url("${url}")` : "none"
}

// Opens the file picker and uploads one public image. `uploading` holds `target` meanwhile, so
// the button that asked can say "Uploading…".
export function uploadImage({ toast, uploading, target, onUploaded }) {
	const input = document.createElement("input")
	input.type = "file"
	input.accept = "image/*"
	input.onchange = () => {
		const file = input.files?.[0]
		if (!file) return
		if (file.size > MAX_IMAGE_BYTES) {
			toast.error("Images must be under 5 MB.")
			return
		}
		uploading.value = target
		useFileUpload()
			.upload(file, { private: false })
			.then((uploaded) => onUploaded(uploaded.file_url || ""))
			.catch(() => toast.error("Couldn't upload that image. Try again."))
			.finally(() => {
				uploading.value = ""
			})
	}
	input.click()
}

// ---- Success stories: the first featured, then a list, filtered by industry ----

// Stories listed under the featured one before "Show all".
const STORIES_LISTED = 4

export function storyIndustryOptions(stories) {
	const industries = [...new Set((stories || []).map((story) => story.category).filter(Boolean))]
	return [{ label: "All Industries", value: "" }, ...industries.map((industry) => ({ label: industry, value: industry }))]
}

export function storyView(stories, industry, showAll) {
	const shown = (stories || []).filter((story) => !industry || story.category === industry)
	const [featured = null, ...rest] = shown
	const listed = showAll ? rest : rest.slice(0, STORIES_LISTED)
	let moreLabel = ""
	if (rest.length > STORIES_LISTED) moreLabel = showAll ? "Show fewer" : `Show all ${shown.length}`
	return {
		featured,
		rows: listed.map((story, index) => ({ ...story, index, last: index === listed.length - 1 })),
		moreLabel,
	}
}

// A story's client logo, in colour as the client made it.
export function storyLogo(story) {
	return story?.client_logo ? `url("${story.client_logo}")` : "none"
}
