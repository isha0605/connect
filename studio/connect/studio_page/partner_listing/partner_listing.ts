// The partner's Listing: their profile laid out the way businesses see it in the directory,
// one section at a time, each with an Edit dialog. Only the partner's admin may edit. Edits wait as
// unpublished changes until Publish makes them live. Reviews come from customers, and success
// stories (with their client logos) are submitted on frappe.io, so those only show.

import { computed, ref } from "vue"
import {
	DEFAULT_ANSWERS,
	MAX_INDUSTRIES,
	PROFILE_API,
	SAMPLE_PROFILE,
	draftProblem,
	imageTile,
	isOverLimit,
	limitCounter,
	toDraft,
	toOptions,
	toSavePayload,
	uploadImage,
} from "@app/utils/partnerProfile"
import { startTracking } from "@app/utils/tracking"

const SUBMIT_STORY_URL = "https://frappe.io/partners"
const REVIEWS_SHOWN = 4
// The public profile shows this many client logos, in one row.
const CLIENT_LOGOS_SHOWN = 6
const SECTION_TITLES = {
	name: "Edit name and tagline",
	photos: "Edit photos",
	details: "Edit details",
	vision: "Edit partner vision",
	answers: "Edit how you work",
}

// What the editor shows for reviews, since the sample profile has none.
const SAMPLE_REVIEWS = [
	{ reviewer_name: "Devika Nair", customer_name: "Nair Engineering Pvt Ltd", rating: 5, reviewed_on: "2026-06-01",
		quote: "They understood our processes before proposing anything." },
	{ reviewer_name: "Harsh Vora", customer_name: "Vora Agro Pvt Ltd", rating: 4, reviewed_on: "2026-05-01",
		quote: "Strong on the finance side and very patient with our questions." },
]

function timeAgo(date) {
	const days = Math.floor((Date.now() - new Date(date).getTime()) / 86400000)
	if (!(days >= 0)) return ""
	if (days < 1) return "Today"
	if (days < 30) return days === 1 ? "Yesterday" : `${days} days ago`
	const months = Math.floor(days / 30)
	if (months < 12) return months === 1 ? "1 month ago" : `${months} months ago`
	const years = Math.floor(months / 12)
	return years === 1 ? "1 year ago" : `${years} years ago`
}

function openInNewTab(url) {
	if (url) window.open(url, "_blank", "noopener")
}

export default function setup(context) {
	startTracking(context)
	const { call, toast, router, editSection } = context

	const profile = ref(null)
	const reviews = ref([])
	const loadError = ref(false)

	const inEditor = window.location.pathname.startsWith("/studio/")
	function load() {
		return call(`${PROFILE_API}.get_my_profile`, { with_draft: 1 })
			.catch((error) => {
				// The editor signed in as someone on no partner's team gets the sample instead.
				if (inEditor) return SAMPLE_PROFILE
				throw error
			})
			.then((data) => {
				profile.value = data
				return call(`${PROFILE_API}.list_partner_reviews`, { partner: data.partner })
			})
			.then((rows) => {
				reviews.value = rows?.length || !inEditor ? rows || [] : SAMPLE_REVIEWS
			})
			.catch(() => {
				loadError.value = !profile.value
			})
	}
	load()

	const canEdit = computed(() => !!profile.value?.can_edit)
	const stories = computed(() => profile.value?.success_stories || [])

	// ---- Name and tagline ----
	const listingName = computed(() => profile.value?.partner_name || "")

	function openDirectory() {
		openInNewTab(router.resolve({ path: `/partner-profile-redesign/${profile.value.partner}` }).href)
	}

	// ---- Photos and video: one large tile, up to two beside it, "+N" for the rest ----
	const photos = computed(() => (profile.value?.photos || []).map((photo, index) => ({ ...photo, index })))
	const sidePhotos = computed(() => {
		const more = photos.value.length - 3
		return photos.value.slice(1, 3).map((photo, index) => ({ ...photo, more: index === 1 && more > 0 ? `+${more}` : "" }))
	})

	// ---- Client logos, from the success stories, as the public profile shows them ----
	const clientLogos = computed(() =>
		stories.value
			.filter((story) => story.client_logo)
			.slice(0, CLIENT_LOGOS_SHOWN)
			.map((story) => ({ ...story, logo: story.client_logo_display || story.client_logo })),
	)

	// ---- Details ----
	const details = computed(() => {
		const p = profile.value || {}
		const pmm = Math.round(Number(p.pmm_level) || 0)
		const certified = [
			p.certs_erpnext ? `${p.certs_erpnext} ERPNext` : "",
			p.certs_frappe_framework ? `${p.certs_frappe_framework} Framework` : "",
		].filter(Boolean)
		return {
			pmm: pmm ? String(pmm) : "Not rated yet",
			certified,
			address: p.address || "Not added yet",
			rate: p.hourly_rate ? `From ₹${Number(p.hourly_rate).toLocaleString("en-IN")}/hr` : "Not added yet",
			countries: p.country ? [p.country] : [],
			industries: p.industry_badges || [],
			apps: p.apps || [],
			migrations: p.migrations || [],
		}
	})

	// ---- Vision: the founder's quote, then the three answers as the public profile shows them ----
	const founder = computed(() => profile.value?.founder || {})
	const answers = computed(() => {
		const p = profile.value || {}
		const rows = [
			{ key: "why_choose_them", icon: "/assets/connect/images/why-work-with-us-icon.svg", label: "Why work with us?" },
			{ key: "how_we_work", icon: "/assets/connect/images/how-we-work-icon.svg", label: "How we'll work together" },
			{ key: "successful_implementation", icon: "/assets/connect/images/successful-implementation-icon.svg",
				label: "How we define a\nsuccessful implementation" },
		]
		return rows.map((row, index) => ({
			...row,
			text: p[row.key] || DEFAULT_ANSWERS[row.key],
			empty: !p[row.key],
			last: index === rows.length - 1,
		}))
	})

	// ---- Reviews ----
	const showAllReviews = ref(false)
	const averageRating = computed(() => {
		const rated = reviews.value.filter((review) => review.rating)
		if (!rated.length) return ""
		return (rated.reduce((sum, review) => sum + Number(review.rating), 0) / rated.length).toFixed(1)
	})
	const shownReviews = computed(() =>
		(showAllReviews.value ? reviews.value : reviews.value.slice(0, REVIEWS_SHOWN)).map((review, index) => ({
			...review,
			index,
			rating: Number(review.rating || 0).toFixed(1),
			when: timeAgo(review.reviewed_on),
		})),
	)

	// ---- Case studies: one large, the rest three to a row ----
	const storyCards = computed(() => stories.value.map((story, index) => ({ ...story, index })))

	// ---- Edit dialog: editSection is a page variable, so the editor can show any section's form ----
	const editOpen = ref(false)
	const draft = ref({})
	const saving = ref(false)
	const saveError = ref("")
	const uploading = ref("")

	function openEdit(section) {
		draft.value = toDraft(profile.value)
		editSection.value = section
		saveError.value = ""
		editOpen.value = true
	}

	function saveSection() {
		if (saving.value) return
		const problem = draftProblem(draft.value, toDraft(profile.value))
		if (problem) {
			saveError.value = problem
			return
		}
		saving.value = true
		saveError.value = ""
		call(`${PROFILE_API}.update_my_partner_profile`, { ...toSavePayload(draft.value), as_draft: 1 })
			.then(() => load())
			.then(() => {
				editOpen.value = false
				toast.success("Saved. Publish to show it to businesses.")
			})
			.catch((error) => {
				saveError.value = error?.messages?.[0] || "Couldn't save your listing. Try again."
			})
			.finally(() => {
				saving.value = false
			})
	}

	const upload = (target, onUploaded) => uploadImage({ toast, uploading, target, onUploaded })

	// ---- Publish: the saved edits go live together; Discard drops them ----
	const hasUnpublished = computed(() => !!profile.value?.has_unpublished_changes)
	const publishing = ref(false)
	const discardOpen = ref(false)
	const discarding = ref(false)

	function publishListing() {
		if (publishing.value) return
		publishing.value = true
		call(`${PROFILE_API}.publish_my_profile_draft`)
			.then(() => load())
			.then(() => toast.success("Published. Businesses now see your changes."))
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't publish your listing. Try again."))
			.finally(() => {
				publishing.value = false
			})
	}

	function discardChanges() {
		if (discarding.value) return
		discarding.value = true
		call(`${PROFILE_API}.discard_my_profile_draft`)
			.then(() => load())
			.then(() => {
				discardOpen.value = false
				toast.success("Unpublished changes discarded")
			})
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't discard your changes. Try again."))
			.finally(() => {
				discarding.value = false
			})
	}

	function uploadLabel(target, empty, replace) {
		if (uploading.value === target) return "Uploading…"
		return replace ? `Replace ${empty}` : `Upload ${empty}`
	}

	const options = computed(() => profile.value?.options || {})

	return {
		profile,
		loadError,
		canEdit,
		hasUnpublished,
		publishing,
		publishListing,
		discardOpen,
		discarding,
		discardChanges,
		listingName,
		openDirectory,
		mainPhoto: computed(() => photos.value[0] || null),
		sidePhotos,
		photoColumns: computed(() => (sidePhotos.value.length ? "minmax(0, 2fr) minmax(0, 1fr)" : "minmax(0, 1fr)")),
		openMedia: (photo) => openInNewTab(photo.video || photo.image),
		clientLogos,
		details,
		founder,
		answers,
		reviews,
		averageRating,
		reviewCount: computed(() => (reviews.value.length === 1 ? "1 review" : `${reviews.value.length} reviews`)),
		shownReviews,
		showAllReviews,
		hasMoreReviews: computed(() => reviews.value.length > REVIEWS_SHOWN),
		featuredStory: computed(() => storyCards.value[0] || null),
		otherStories: computed(() => storyCards.value.slice(1)),
		storyCount: computed(() => String(stories.value.length)),
		openStory: (story) => openInNewTab(story.url),
		submitStory: () => openInNewTab(SUBMIT_STORY_URL),
		imageTile,
		// edit dialog
		editOpen,
		editTitle: computed(() => SECTION_TITLES[editSection.value] || "Edit listing"),
		openEdit,
		draft,
		saving,
		saveError,
		saveSection,
		counter: (path) => limitCounter(draft.value, path),
		isOver: (path) => isOverLimit(draft.value, path),
		uploading,
		uploadLabel,
		uploadLogo: () => upload("logo", (url) => (draft.value.logo = url)),
		uploadMark: () => upload("logo_icon", (url) => (draft.value.logo_icon = url)),
		uploadFounderPhoto: () => upload("founder", (url) => (draft.value.founder.photo = url)),
		addPhoto: () => upload("gallery", (url) => draft.value.photos.push({ image: url, video: "" })),
		removePhoto: (index) => draft.value.photos.splice(index, 1),
		draftPhotos: computed(() => (draft.value.photos || []).map((photo, index) => ({ ...photo, index }))),
		industryOptions: computed(() => toOptions(options.value.industries)),
		industryCount: computed(() => `${(draft.value.industries || []).length} of ${MAX_INDUSTRIES}`),
		tooManyIndustries: computed(() => (draft.value.industries || []).length > MAX_INDUSTRIES),
		// industries their stories prove that they haven't picked yet
		industrySuggestions: computed(() =>
			(profile.value?.suggested_industries || [])
				.filter((row) => !(draft.value.industries || []).includes(row.industry))
				.map((row) => ({ ...row, label: `${row.industry} · ${row.stories} stories` })),
		),
		addIndustry: (industry) => {
			const picked = draft.value.industries || []
			if (picked.length < MAX_INDUSTRIES && !picked.includes(industry)) draft.value.industries = [...picked, industry]
		},
		appOptions: computed(() => toOptions(options.value.apps)),
		migrationOptions: computed(() => toOptions(options.value.migrations)),
	}
}
