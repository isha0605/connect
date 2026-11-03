// The partner's Profile builder: an input for everything their public profile shows
// (connect.api.partner.get_my_profile), saved by update_my_partner_profile. Only the partner's
// admin may edit; everyone else on the team reads it. Preview opens the public profile in a new
// tab with the unsaved changes laid over it (@app/utils/profilePreview).

import { computed, onScopeDispose, ref, watch } from "vue"
import { EMPLOYEE_OPTIONS } from "@app/utils/recommendation"
import { writePreview } from "@app/utils/profilePreview"
import {
	LIMITS,
	MAX_INDUSTRIES,
	PROFILE_API,
	SAMPLE_PROFILE,
	STORY_LIMITS,
	draftProblem,
	imageTile,
	overLimitPaths,
	isBlank,
	isOverLimit,
	isStoryOver,
	limitCounter,
	storyCounter,
	toDraft,
	toOptions,
	toSavePayload,
	uploadImage,
	valueAt,
} from "@app/utils/partnerProfile"
import { startTracking } from "@app/utils/tracking"

// The builder's tabs, in the public profile's order, and the fields each counts as empty
// ("About 1") when left blank.
const TABS = [
	{ key: "basics", label: "Basics", fields: ["logo", "tagline", "website", "phone"] },
	{ key: "about", label: "About", fields: ["description", "year_founded", "team_size", "rollouts", "address"] },
	{ key: "services", label: "Services", fields: ["industries", "apps", "migrations"] },
	{ key: "vision", label: "Partner vision", fields: ["why_choose_them", "how_we_work", "successful_implementation"] },
	{ key: "founder", label: "Founder", fields: ["founder.member_name", "founder.bio"] },
	{ key: "gallery", label: "Gallery", fields: ["photos"] },
	{ key: "stories", label: "Success stories", fields: ["success_stories"] },
	{ key: "story", label: "Your story", fields: ["origin_story"] },
]

export default function setup(context) {
	startTracking(context)
	const { call, toast, router, activeTab } = context

	const profile = ref(null)
	const loadError = ref(false)
	// A ref, not reactive(): Studio writes nested v-model paths ("draft.tagline") only into refs.
	const draft = ref({})
	const savedDraft = ref("")

	function fillDraft(data) {
		profile.value = data
		draft.value = toDraft(data)
		savedDraft.value = JSON.stringify(draft.value)
	}

	const inEditor = window.location.pathname.startsWith("/studio/")
	function load() {
		return call(`${PROFILE_API}.get_my_profile`)
			.then(fillDraft)
			.catch(() => {
				// The editor signed in as someone on no partner's team gets the sample instead.
				if (inEditor) fillDraft(SAMPLE_PROFILE)
				else loadError.value = true
			})
	}
	load()

	const canEdit = computed(() => !!profile.value?.can_edit)
	const hasChanges = computed(() => !!profile.value && JSON.stringify(draft.value) !== savedDraft.value)

	// ---- Tabs: activeTab is a page variable, so the editor can switch tabs from the Data panel ----
	const tabs = computed(() =>
		TABS.map((tab, index) => {
			const empty = tab.fields.filter((path) => isBlank(valueAt(draft.value, path))).length
			return { ...tab, index, empty, active: tab.key === activeTab.value }
		}),
	)
	const tabIndex = computed(() => TABS.findIndex((tab) => tab.key === activeTab.value))
	const previousTab = computed(() => TABS[tabIndex.value - 1] || null)
	const nextTab = computed(() => TABS[tabIndex.value + 1] || null)

	function selectTab(key) {
		activeTab.value = key
	}

	// ---- Leaving with unsaved changes ----
	function warnOnUnload(event) {
		if (!hasChanges.value) return
		event.preventDefault()
		event.returnValue = ""
	}
	window.addEventListener("beforeunload", warnOnUnload)
	const stopGuard = router.beforeEach((to, from) => {
		if (from.path === to.path || !hasChanges.value) return true
		return window.confirm("You have unsaved changes to your profile. Leave without saving?")
	})
	onScopeDispose(() => {
		window.removeEventListener("beforeunload", warnOnUnload)
		stopGuard()
	})
	const options = computed(() => profile.value?.options || {})

	// The preview tab reads this as the partner types.
	watch(draft, (value) => profile.value && writePreview(profile.value.partner, value), { deep: true })

	function openPreview() {
		writePreview(profile.value.partner, draft.value)
		const href = router.resolve({
			path: `/partner-profile-redesign/${profile.value.partner}`,
			query: { preview: "1" },
		}).href
		window.open(href, "_blank", "noopener")
	}

	// ---- Uploads: logo, mark, founder photo, gallery, a story's client logo ----
	const uploading = ref("")

	const upload = (target, onUploaded) => uploadImage({ toast, uploading, target, onUploaded })
	const uploadLogo = () => upload("logo", (url) => (draft.value.logo = url))
	const uploadMark = () => upload("logo_icon", (url) => (draft.value.logo_icon = url))
	const uploadFounderPhoto = () => upload("founder", (url) => (draft.value.founder.photo = url))
	const addPhoto = () => upload("gallery", (url) => draft.value.photos.push({ image: url, video: "" }))

	function removePhoto(index) {
		draft.value.photos.splice(index, 1)
	}

	function uploadLabel(target, empty, replace) {
		if (uploading.value === target) return "Uploading…"
		return replace ? `Replace ${empty}` : `Upload ${empty}`
	}

	// ---- Success stories: edited one at a time in a dialog ----
	const storyOpen = ref(false)
	const storyIndex = ref(-1)
	const story = ref({})
	const storyError = ref("")

	function openStory(index) {
		storyIndex.value = index
		story.value = { client_name: "", headline: "", category: "", url: "", client_logo: "", ...(draft.value.success_stories[index] || {}) }
		storyError.value = ""
		storyOpen.value = true
	}

	function saveStory() {
		if (!String(story.value.client_name || "").trim() || !String(story.value.headline || "").trim()) {
			storyError.value = "Add the client's name and a headline."
			return
		}
		const tooLong = ["client_name", "headline"].find((field) => isStoryOver(story.value, field))
		if (tooLong) {
			storyError.value = `Shorten the ${tooLong === "headline" ? "headline" : "client's name"} to ${STORY_LIMITS[tooLong]} characters.`
			return
		}
		const stories = draft.value.success_stories
		if (storyIndex.value < 0) stories.push({ ...story.value })
		else stories.splice(storyIndex.value, 1, { ...story.value })
		storyOpen.value = false
	}

	function removeStory(index) {
		draft.value.success_stories.splice(index, 1)
	}

	const uploadStoryLogo = () => upload("story", (url) => (story.value.client_logo = url))

	// ---- Save ----
	const saving = ref(false)
	const saveError = ref("")

	function saveProfile() {
		if (saving.value || !hasChanges.value) return
		const problem = draftProblem(draft.value, JSON.parse(savedDraft.value))
		if (problem) {
			const over = overLimitPaths(draft.value, JSON.parse(savedDraft.value))[0]
			if (over) activeTab.value = LIMITS[over].tab
			saveError.value = problem
			return
		}
		saving.value = true
		saveError.value = ""
		call(`${PROFILE_API}.update_my_partner_profile`, toSavePayload(draft.value))
			.then(() => load())
			.then(() => toast.success("Profile saved"))
			.catch((error) => {
				saveError.value = error?.messages?.[0] || "Couldn't save your profile. Try again."
			})
			.finally(() => {
				saving.value = false
			})
	}

	// Counted from linked certificates on the server, so they show here but aren't edited.
	const certSummary = computed(() => {
		const p = profile.value || {}
		return `${p.certs_erpnext || 0} ERPNext · ${p.certs_frappe_framework || 0} Framework`
	})

	return {
		tabs,
		selectTab,
		previousTab,
		nextTab,
		certSummary,
		openCertifications: () => router.push("/partner-certifications"),
		counter: (path) => limitCounter(draft.value, path),
		isOver: (path) => isOverLimit(draft.value, path),
		storyCounter: (field) => storyCounter(story.value, field),
		storyOver: (field) => isStoryOver(story.value, field),
		profile,
		loadError,
		draft,
		canEdit,
		hasChanges,
		saving,
		saveError,
		saveProfile,
		openPreview,
		partnerName: computed(() => profile.value?.partner_name || ""),
		setByFrappe: computed(() => {
			const p = profile.value || {}
			const pmm = Math.round(Number(p.pmm_level) || 0)
			return `Tier: ${p.tier || "not set"} · PMM level: ${pmm || "not rated yet"}. Frappe sets these.`
		}),
		teamSizeOptions: [{ label: "Select", value: "" }, ...EMPLOYEE_OPTIONS],
		industryOptions: computed(() => toOptions(options.value.industries)),
		industryCount: computed(() => `${(draft.value.industries || []).length} of ${MAX_INDUSTRIES}`),
		tooManyIndustries: computed(() => (draft.value.industries || []).length > MAX_INDUSTRIES),
		appOptions: computed(() => toOptions(options.value.apps)),
		migrationOptions: computed(() => toOptions(options.value.migrations)),
		categoryOptions: computed(() => options.value.categories || []),
		uploading,
		uploadLogo,
		uploadMark,
		uploadFounderPhoto,
		uploadLabel,
		imageTile,
		galleryTiles: computed(() => (draft.value.photos || []).map((photo, index) => ({ ...photo, index }))),
		addPhoto,
		removePhoto,
		storyRows: computed(() => (draft.value.success_stories || []).map((row, index) => ({ ...row, index }))),
		storyOpen,
		story,
		storyError,
		storyTitle: computed(() => (storyIndex.value < 0 ? "Add a success story" : "Edit success story")),
		openStory,
		saveStory,
		removeStory,
		uploadStoryLogo,
	}
}
