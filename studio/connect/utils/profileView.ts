// What the shared profile sections show: the Studio components partnerprofilesections (photos to
// "In their words") and partnerprofilestories (Featured by Frappe and Success stories). The Listing
// and the public profile both spread this into their setup's return, so the sections read the same
// names on either page. Each page passes its own profile record and the stories in the order to show.

import { computed, ref } from "vue"
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

const ANSWER_ICONS = "/assets/connect/images"
// The three questions, in the order "In their words" asks them.
const ANSWERS = [
	{ key: "origin_story", icon: `${ANSWER_ICONS}/how-we-got-here-icon.svg`, label: "How we got here" },
	{ key: "why_choose_them", icon: `${ANSWER_ICONS}/why-work-with-us-icon.svg`, label: "Why work with us and who should work with us" },
	{ key: "how_we_work", icon: `${ANSWER_ICONS}/how-we-work-icon.svg`, label: "How we'll work together" },
]
// The grid shows the cover and two more; the second of those says how many more there are.
const GALLERY_TILES = 3
export const STORIES_SECTION = "stories-section"

export function openInNewTab(url) {
	if (url) window.open(url, "_blank", "noopener")
}

// profile, stories and isEditing are refs or computeds; selectedStoryIndustry is the page's variable.
export function useProfileView({ profile, stories, isEditing, selectedStoryIndustry }) {
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
		return {
			pmm: pmm ? String(pmm) : "Not rated yet",
			certified: [
				p.certs_erpnext ? `${p.certs_erpnext} ERPNext` : "",
				p.certs_frappe_framework ? `${p.certs_frappe_framework} Framework` : "",
			].filter(Boolean),
			offices: p.offices || [],
			rate: p.hourly_rate ? `From ₹${Number(p.hourly_rate).toLocaleString("en-IN")}/hr` : "Not added yet",
			industries: p.industry_badges || [],
			apps: p.apps || [],
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
	}
}
