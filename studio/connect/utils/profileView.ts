// What the shared profile sections show: the Studio components partnerprofilesections (photos to
// "In their words") and partnerprofilestories (Featured by Frappe and Success stories). The Listing
// and the public profile both spread this into their setup's return, so the sections read the same
// names on either page. Each page passes its own profile record and the stories in the order to show.
// On the public profile (forCustomers) a section with nothing in it is left out, since its empty
// note speaks to the partner ("Add your founder…"); the partner's own Listing keeps the notes.

import { computed, ref } from "vue"
import { currencySymbol, hourlyRate } from "@app/utils/money"
import {
	DEFAULT_ANSWERS,
	MIN_CLIENT_LOGOS,
	clientLogoCount,
	clientLogoRow,
	featureRows,
	imageTile,
	orderedLogoStories,
	storyIndustryOptions,
	storyLogo,
	storyView,
} from "@app/utils/partnerProfile"

// The three questions, in the order "In their words" asks them.
const ANSWERS = [
	{ key: "origin_story", icon: "lucide-book-open", label: "How we got here" },
	{ key: "why_choose_them", icon: "lucide-unplug", label: "Why work with us and who should work with us" },
	{ key: "how_we_work", icon: "lucide-wrench", label: "How we'll work together" },
]
// The grid shows the cover and two more; the second of those says how many more there are.
const GALLERY_TILES = 3
export const STORIES_SECTION = "stories-section"

export function openInNewTab(url) {
	if (url) window.open(url, "_blank", "noopener")
}

// profile, stories and isEditing are refs or computeds; selectedStoryIndustry is the page's variable.
// viewerCurrency, a ref, is the customer's currency for the rough amount beside the rate.
export function useProfileView({ profile, stories, isEditing, selectedStoryIndustry, forCustomers = false, viewerCurrency = null }) {
	const photos = computed(() => (profile.value?.photos || []).map((photo, index) => ({ ...photo, index })))
	const sidePhotos = computed(() => {
		const more = photos.value.length - GALLERY_TILES
		return photos.value.slice(1, GALLERY_TILES).map((photo, index) => ({ ...photo, more: index === 1 && more > 0 ? `+${more}` : "" }))
	})

	// Shown instead of the row: why the public profile has no logos yet.
	const clientLogosNote = computed(() => {
		const count = clientLogoCount(stories.value)
		if (!orderedLogoStories(stories.value).length) return "No client logos yet. They come from your success stories."
		if (count < MIN_CLIENT_LOGOS) return `The logo row shows on your profile once it has ${MIN_CLIENT_LOGOS} logos. It has ${count}.`
		return ""
	})

	const details = computed(() => {
		const p = profile.value || {}
		const pmm = Math.round(Number(p.pmm_level) || 0)
		// An app chip shows the app's logo, when it has one.
		const logos = p.app_logos || {}
		return {
			pmm: pmm ? String(pmm) : "Not rated yet",
			certified: [
				p.erpnext_certified ? { label: `${p.erpnext_certified} ERPNext` } : null,
				p.framework_certified ? { label: `${p.framework_certified} Framework` } : null,
			].filter(Boolean),
			offices: p.offices || [],
			rate: p.hourly_rate ? hourlyRate(p.hourly_rate, p.currency, viewerCurrency?.value) : "Not added yet",
			industries: p.industry_badges || [],
			// The partner's own picks, then the apps their success stories name on frappe.io.
			apps: [...new Set([...(p.apps || []), ...(p.story_apps || [])])].map((app) => ({ label: app, logo: logos[app] || "" })),
			migrations: p.migrations || [],
		}
	})

	// An empty answer shows Frappe's default text where there is one.
	const answers = computed(() => {
		const p = profile.value || {}
		return ANSWERS.map((row, index) => ({
			...row,
			text: p[row.key] || DEFAULT_ANSWERS[row.key] || "Not added yet.",
			empty: !p[row.key],
			defaulted: !p[row.key] && !!DEFAULT_ANSWERS[row.key],
			last: index === ANSWERS.length - 1,
		}))
	})

	// One story featured, then a list, filtered by industry except while the order is being set.
	const showAllStories = ref(false)
	const shownStories = computed(() =>
		storyView(
			stories.value.map((story, position) => ({ ...story, position })),
			isEditing.value ? "" : selectedStoryIndustry.value,
			showAllStories.value,
		),
	)

	// A verified industry has stories behind it: show only those, where the stories are.
	function showStoriesFor(industry) {
		selectedStoryIndustry.value = industry
		document.querySelector(`[data-component-id="${STORIES_SECTION}"]`)?.scrollIntoView({ behavior: "smooth" })
	}

	return {
		mainPhoto: computed(() => photos.value[0] || null),
		sidePhotos,
		photoColumns: computed(() => (sidePhotos.value.length ? "minmax(0, 2fr) minmax(0, 1fr)" : "minmax(0, 1fr)")),
		clientLogos: computed(() => clientLogoRow(stories.value)),
		clientLogosNote,
		details,
		// Beside the rate box in the Listing editor: the partner types their rate in their currency.
		rateSymbol: computed(() => currencySymbol(profile.value?.currency)),
		founder: computed(() => profile.value?.founder || {}),
		answers,
		featureRows: computed(() => featureRows(profile.value?.features)),
		openFeature: (feature) => openInNewTab(feature.url),
		storyView: shownStories,
		storyCount: computed(() => String(stories.value.length)),
		storyIndustryOptions: computed(() => storyIndustryOptions(stories.value)),
		storyLogo,
		showAllStories,
		showStoriesFor,
		openStory: (story) => openInNewTab(story?.url),
		imageTile,
		showEmptyNotes: !forCustomers,
	}
}
