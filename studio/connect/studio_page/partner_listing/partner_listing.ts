// The partner's Listing: their profile laid out the way businesses see it in the directory. The
// partner's admin edits it in place (Edit), or sees it as businesses will (Preview). Edits save as
// they type, as unpublished changes, until Publish makes them live. Reviews come from customers, and
// success stories (with their client logos) are submitted on frappe.io, so those only show.

import { computed, ref, watch } from "vue"
import {
	DEFAULT_ANSWERS,
	MAX_INDUSTRIES,
	MIN_CLIENT_LOGOS,
	PROFILE_API,
	SAMPLE_PROFILE,
	clientLogoCount,
	clientLogoRow,
	imageTile,
	isOverLimit,
	limitCounter,
	storyIndustryOptions,
	storyLogo,
	storyView,
	toDraft,
	toOptions,
	uploadImage,
} from "@app/utils/partnerProfile"
import { useProfileAutosave } from "@app/utils/profileAutosave"
import { startTracking } from "@app/utils/tracking"

const SUBMIT_STORY_URL = "https://frappe.io/partners"
const REVIEWS_SHOWN = 4
const STORIES_SECTION = "stories-section"
const ANSWER_ICONS = "/assets/connect/images"
// Delivery Mode records as the Listing words them.
const DELIVERY_LABELS = { Onsite: "On site" }
const deliveryLabel = (mode) => DELIVERY_LABELS[mode] || mode

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
	const { call, toast, listingMode, selectedStoryIndustry } = context

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
				draft.value = toDraft(data)
				autosave.reset()
				return call(`${PROFILE_API}.list_partner_reviews`, { partner: data.partner })
			})
			.then((rows) => {
				reviews.value = rows?.length || !inEditor ? rows || [] : SAMPLE_REVIEWS
			})
			.catch(() => {
				loadError.value = !profile.value
			})
	}

	// ---- Editing in place: the draft is the whole profile, saved as the partner types ----
	const draft = ref({})
	const uploading = ref("")
	const autosave = useProfileAutosave({
		call,
		draft,
		profile,
		uploading,
		// The page shows the saved draft; the fields keep what the partner is typing.
		onSaved: () => call(`${PROFILE_API}.get_my_profile`, { with_draft: 1 }).then((data) => (profile.value = data)),
	})
	load()

	const canEdit = computed(() => !!profile.value?.can_edit)
	const isEditing = computed(() => canEdit.value && listingMode.value === "edit")
	// Preview shows what's saved, so save what's waiting first.
	watch(listingMode, (mode) => mode === "preview" && autosave.flush())
	const stories = computed(() => profile.value?.success_stories || [])

	// ---- Name and tagline ----
	const listingName = computed(() => profile.value?.partner_name || "")

	// ---- Photos and video: one large tile, up to two beside it, "+N" for the rest ----
	const photos = computed(() => (profile.value?.photos || []).map((photo, index) => ({ ...photo, index })))
	const sidePhotos = computed(() => {
		const more = photos.value.length - 3
		return photos.value.slice(1, 3).map((photo, index) => ({ ...photo, more: index === 1 && more > 0 ? `+${more}` : "" }))
	})

	// ---- Client logos, from the success stories, as the public profile shows them ----
	const clientLogos = computed(() => clientLogoRow(stories.value))
	// Shown instead of the row: why the public profile has no logos yet.
	const clientLogosNote = computed(() => {
		const count = clientLogoCount(stories.value)
		if (!count) return "No client logos yet. They come from your success stories."
		return `Your client logos show on your profile once ${MIN_CLIENT_LOGOS} success stories have a logo. You have ${count}.`
	})

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
			// Until a partner lists the countries it serves, show its own country.
			countries: p.served_countries?.length ? p.served_countries : p.country ? [p.country] : [],
			industries: p.industry_badges || [],
			apps: p.apps || [],
			migrations: p.migrations || [],
			works: (p.delivery_options || []).map(deliveryLabel),
		}
	})

	// ---- Vision: the founder's quote, then the three answers as the public profile shows them ----
	const founder = computed(() => profile.value?.founder || {})
	const answers = computed(() => {
		const p = profile.value || {}
		const rows = [
			{ key: "origin_story", icon: `${ANSWER_ICONS}/how-we-got-here-icon.svg`, label: "How we got here" },
			{ key: "why_choose_them", icon: `${ANSWER_ICONS}/why-work-with-us-icon.svg`, label: "Why work with us and who should work with us" },
			{ key: "how_we_work", icon: `${ANSWER_ICONS}/how-we-work-icon.svg`, label: "How we'll work together" },
		]
		return rows.map((row, index) => ({
			...row,
			text: p[row.key] || DEFAULT_ANSWERS[row.key] || "Not added yet.",
			empty: !p[row.key],
			// an empty answer shows Frappe's default text where there is one
			defaulted: !p[row.key] && !!DEFAULT_ANSWERS[row.key],
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

	// ---- Success stories: one featured, then a list, filtered by industry as on the public profile ----
	const showAllStories = ref(false)
	// Hide folds the section away while editing; the public profile always shows it.
	const storiesCollapsed = ref(false)

	// A verified industry has stories behind it: show only those, where the stories are.
	function showStoriesFor(industry) {
		selectedStoryIndustry.value = industry
		storiesCollapsed.value = false
		document.querySelector(`[data-component-id="${STORIES_SECTION}"]`)?.scrollIntoView({ behavior: "smooth" })
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
		autosave
			.flush()
			.then(() => {
				if (!autosave.isSaved()) throw { messages: [autosave.status.value || "Wait for your changes to save, then publish."] }
				return call(`${PROFILE_API}.publish_my_profile_draft`)
			})
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
		isEditing,
		saveStatus: autosave.status,
		hasSaveProblem: autosave.hasProblem,
		mainPhoto: computed(() => photos.value[0] || null),
		sidePhotos,
		photoColumns: computed(() => (sidePhotos.value.length ? "minmax(0, 2fr) minmax(0, 1fr)" : "minmax(0, 1fr)")),
		openMedia: (photo) => openInNewTab(photo.video || photo.image),
		clientLogos,
		clientLogosNote,
		details,
		founder,
		answers,
		reviews,
		averageRating,
		reviewCount: computed(() => (reviews.value.length === 1 ? "1 review" : `${reviews.value.length} reviews`)),
		shownReviews,
		showAllReviews,
		hasMoreReviews: computed(() => reviews.value.length > REVIEWS_SHOWN),
		storyView: computed(() => storyView(stories.value, selectedStoryIndustry.value, showAllStories.value)),
		storyCount: computed(() => String(stories.value.length)),
		storyIndustryOptions: computed(() => storyIndustryOptions(stories.value)),
		storyLogo,
		showAllStories,
		storiesCollapsed,
		showStoriesFor,
		openStory: (story) => openInNewTab(story.url),
		submitStory: () => openInNewTab(SUBMIT_STORY_URL),
		imageTile,
		// editing in place
		draft,
		counter: (path) => limitCounter(draft.value, path),
		isOver: (path) => isOverLimit(draft.value, path),
		uploading,
		uploadLabel,
		uploadLogo: () => upload("logo", (url) => (draft.value.logo = url)),
		uploadMark: () => upload("logo_icon", (url) => (draft.value.logo_icon = url)),
		uploadFounderPhoto: () => upload("founder", (url) => (draft.value.founder.photo = url)),
		// the gallery editor (GalleryEditor.vue) hands back the whole list after each change
		setDraftPhotos: (photos) => (draft.value.photos = photos),
		setGalleryUploading: (busy) => (uploading.value = busy ? "gallery" : ""),
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
		deliveryOptions: computed(() =>
			(options.value.delivery_modes || []).map((mode) => ({ label: deliveryLabel(mode), value: mode })),
		),
	}
}
