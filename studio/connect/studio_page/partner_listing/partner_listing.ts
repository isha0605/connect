// The partner's Listing: their profile as businesses see it in the directory. The partner's admin
// edits it in place (Edit profile) and checks it as businesses will see it (Preview). Edits save as
// they type, as unpublished changes, until Publish makes them live or Cancel drops them. Reviews come
// from customers, and success stories (with their client logos) are submitted on frappe.io, so the
// admin only orders those.

import { computed, ref, watch } from "vue"
import {
	CLIENT_LOGOS_SHOWN,
	MAX_INDUSTRIES,
	MAX_OFFICES,
	OFFICE_LIMITS,
	PROFILE_API,
	SAMPLE_PROFILE,
	imageTile,
	isOverLimit,
	limitCounter,
	orderedLogoStories,
	toDraft,
	toOptions,
	uploadImage,
} from "@app/utils/partnerProfile"
import { useProfileAutosave } from "@app/utils/profileAutosave"
import { openInNewTab, useProfileView } from "@app/utils/profileView"
import { startTracking } from "@app/utils/tracking"
import { useMyContext } from "@app/utils/myContext"

const SUBMIT_STORY_URL = "https://frappe.io/partners"
const REVIEWS_SHOWN = 4

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

export default function setup(context) {
	startTracking(context)
	const { call, router, toast, listingMode, selectedStoryIndustry } = context

	// What businesses see now, and the same with the admin's unpublished changes.
	const liveProfile = ref(null)
	const draftProfile = ref(null)
	const reviews = ref([])
	const loadError = ref(false)

	const inEditor = window.location.pathname.startsWith("/studio/")
	const fetchProfile = (withDraft) =>
		call(`${PROFILE_API}.get_my_profile`, { with_draft: withDraft }).catch((error) => {
			// The editor signed in as someone on no partner's team gets the sample instead.
			if (inEditor) return SAMPLE_PROFILE
			throw error
		})

	function load() {
		return fetchProfile(0)
			.then((live) => Promise.all([live, live.can_edit ? fetchProfile(1) : live]))
			.then(([live, withDraft]) => {
				liveProfile.value = live
				draftProfile.value = withDraft
				draft.value = toDraft(withDraft)
				autosave.reset()
				return call(`${PROFILE_API}.list_partner_reviews`, { partner: live.partner })
			})
			.then((rows) => {
				reviews.value = rows?.length || !inEditor ? rows || [] : SAMPLE_REVIEWS
			})
			.catch(() => {
				loadError.value = !liveProfile.value
			})
	}

	// ---- Editing in place: the draft is the whole profile, saved as the partner types ----
	const draft = ref({})
	const uploading = ref("")
	const autosave = useProfileAutosave({
		call,
		draft,
		profile: draftProfile,
		uploading,
		// The page shows the saved draft; the fields keep what the partner is typing.
		onSaved: () => fetchProfile(1).then((data) => (draftProfile.value = data)),
	})
	load()

	// view: what businesses see now. edit and preview: the admin's changes, in place or as businesses will see them.
	const canEdit = computed(() => !!liveProfile.value?.can_edit)
	const isViewing = computed(() => !canEdit.value || listingMode.value === "view")
	const isEditing = computed(() => canEdit.value && listingMode.value === "edit")
	const profile = computed(() => (isViewing.value ? liveProfile.value : draftProfile.value))
	// Preview shows what's saved, so save what's waiting first.
	watch(listingMode, (mode) => mode === "preview" && autosave.flush())
	// While editing, the stories follow the order being set; otherwise, the saved order.
	const stories = computed(() => (isEditing.value ? draft.value.success_stories : profile.value?.success_stories) || [])
	// What the shared profile sections show, the same as on the public profile.
	const view = useProfileView({ profile, stories, isEditing, selectedStoryIndustry })

	// ---- Name and tagline ----
	const listingName = computed(() => profile.value?.company_name || "")
	const markImage = computed(() => imageTile(draft.value.logo_icon || draft.value.logo))

	function copyProfileLink() {
		const path = router.resolve(`/partner-profile-redesign/${encodeURIComponent(liveProfile.value.partner)}`).href
		const link = new URL(path, window.location.origin).href
		navigator.clipboard
			.writeText(link)
			.then(() => toast.success("Link copied"))
			.catch(() => toast.info(link, { description: "Your browser blocked the clipboard. Copy the link from here." }))
	}

	// ---- Client logos ----
	// While editing, every logo in the order being set. Hidden ones, and any past the row's six, are faded.
	const editLogos = computed(() => {
		let shown = 0
		const ordered = orderedLogoStories(stories.value)
		return ordered.map((story, index) => {
			const isShown = !story.hide_logo && ++shown <= CLIENT_LOGOS_SHOWN
			return { ...story, index, last: index === ordered.length - 1, logo: story.client_logo_display || story.client_logo, faded: !isShown }
		})
	})
	const editLogosNote = computed(() => {
		if (view.clientLogosNote.value) return view.clientLogosNote.value
		const isTrimmed = editLogos.value.some((logo) => logo.faded)
		const notes = [
			editLogos.value.length > 1 ? "Drag to reorder, or use each logo's menu." : "",
			isTrimmed ? `Your profile shows the first ${CLIENT_LOGOS_SHOWN} logos you haven't hidden.` : "",
		]
		return notes.filter(Boolean).join(" ")
	})

	// A logo's order is its own, so moving one never changes which story is featured.
	function moveLogo(from, to) {
		const ordered = [...editLogos.value]
		ordered.splice(to, 0, ...ordered.splice(from, 1))
		ordered.forEach((logo, index) => (draft.value.success_stories[logo.position].logo_position = index + 1))
	}

	// Dropping a logo on another puts it there, as with the photos and videos.
	const draggedLogo = ref(null)
	const logoDropIndex = ref(null)

	function onLogoDragStart(index, event) {
		draggedLogo.value = index
		event.dataTransfer.effectAllowed = "move"
		// Firefox starts a drag only when it carries data.
		event.dataTransfer.setData("text/plain", String(index))
	}

	function onLogoDragOver(index) {
		if (draggedLogo.value !== null) logoDropIndex.value = index
	}

	function onLogoDrop(index) {
		if (draggedLogo.value !== null && draggedLogo.value !== index) moveLogo(draggedLogo.value, index)
		onLogoDragEnd()
	}

	function onLogoDragEnd() {
		draggedLogo.value = null
		logoDropIndex.value = null
	}

	function clientLogoMenu(logo) {
		const toggle = () => (draft.value.success_stories[logo.position].hide_logo = logo.hide_logo ? 0 : 1)
		return [
			{ label: "View story", icon: "lucide-external-link", condition: () => !!logo.url, onClick: () => openInNewTab(logo.url) },
			{ label: "Move earlier", icon: "lucide-chevron-left", condition: () => logo.index > 0, onClick: () => moveLogo(logo.index, logo.index - 1) },
			{ label: "Move later", icon: "lucide-chevron-right", condition: () => !logo.last, onClick: () => moveLogo(logo.index, logo.index + 1) },
			{ label: logo.hide_logo ? "Show" : "Hide", icon: logo.hide_logo ? "lucide-eye" : "lucide-eye-off", onClick: toggle },
		]
	}

	// ---- Offices: added and changed in a dialog, saved with the rest of the draft ----
	const officeDialogOpen = ref(false)
	// null while adding one
	const officeIndex = ref(null)
	const officeForm = ref({ city: "", address: "" })
	const officeError = ref("")
	watch(officeForm, () => (officeError.value = ""), { deep: true })

	function openOffice(index = null) {
		officeIndex.value = index
		officeForm.value = index === null ? { city: "", address: "" } : { ...draft.value.offices[index] }
		officeError.value = ""
		officeDialogOpen.value = true
	}

	function officeProblem(office) {
		if (!office.city || !office.address) return "Add the city and the address."
		if (office.city.length > OFFICE_LIMITS.city) return `Shorten the city to ${OFFICE_LIMITS.city} characters.`
		if (office.address.length > OFFICE_LIMITS.address) return `Shorten the address to ${OFFICE_LIMITS.address} characters.`
		return ""
	}

	function saveOffice() {
		const office = { city: officeForm.value.city.trim(), address: officeForm.value.address.trim() }
		officeError.value = officeProblem(office)
		if (officeError.value) return
		const offices = [...draft.value.offices]
		if (officeIndex.value === null) offices.push(office)
		else offices[officeIndex.value] = office
		draft.value.offices = offices
		officeDialogOpen.value = false
	}

	function removeOffice() {
		draft.value.offices = draft.value.offices.filter((_office, index) => index !== officeIndex.value)
		officeDialogOpen.value = false
	}

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

	// ---- Success stories ----
	// The first story is the featured one, so featuring a story moves it to the top.
	function moveStory(from, to) {
		const ordered = [...draft.value.success_stories]
		ordered.splice(to, 0, ...ordered.splice(from, 1))
		draft.value.success_stories = ordered
	}

	function storyMenu(story) {
		const last = stories.value.length - 1
		return [
			{ label: "Feature this story", icon: "lucide-star", condition: () => story.position > 0, onClick: () => moveStory(story.position, 0) },
			{ label: "Move up", icon: "lucide-chevron-up", condition: () => story.position > 1, onClick: () => moveStory(story.position, story.position - 1) },
			{ label: "Move down", icon: "lucide-chevron-down", condition: () => story.position < last, onClick: () => moveStory(story.position, story.position + 1) },
			{ label: "Read story", icon: "lucide-external-link", condition: () => !!story.url, onClick: () => openInNewTab(story.url) },
		]
	}

	const upload = (target, onUploaded) => uploadImage({ toast, uploading, target, onUploaded })

	// ---- Publish: the saved edits go live together; Cancel drops them ----
	const hasUnpublished = computed(() => !!draftProfile.value?.has_unpublished_changes)
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
				// Nothing changed: there's nothing to publish, so just leave editing.
				if (!hasUnpublished.value) return false
				return call(`${PROFILE_API}.publish_my_profile_draft`).then(() => load()).then(() => true)
			})
			.then((published) => {
				listingMode.value = "view"
				if (published) toast.success("Published. Businesses now see your changes.")
			})
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't publish your listing. Try again."))
			.finally(() => {
				publishing.value = false
			})
	}

	// Leaves editing; asks first when there are changes to throw away.
	function cancelEditing() {
		autosave.flush().then(() => {
			if (hasUnpublished.value || !autosave.isSaved()) discardOpen.value = true
			else listingMode.value = "view"
		})
	}

	function discardChanges() {
		if (discarding.value) return
		discarding.value = true
		call(`${PROFILE_API}.discard_my_profile_draft`)
			.then(() => load())
			.then(() => {
				discardOpen.value = false
				listingMode.value = "view"
				toast.success("Changes discarded")
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
		myContext: useMyContext(),
		...view,
		profile,
		loadError,
		canEdit,
		hasUnpublished,
		publishing,
		publishListing,
		discardOpen,
		discarding,
		discardChanges,
		cancelEditing,
		listingName,
		markImage,
		copyProfileLink,
		isViewing,
		isEditing,
		saveStatus: autosave.status,
		hasSaveProblem: autosave.hasProblem,
		openMedia: (photo) => openInNewTab(photo.video || photo.image),
		editLogos,
		editLogosNote,
		clientLogoMenu,
		draggedLogo,
		logoDropIndex,
		onLogoDragStart,
		onLogoDragOver,
		onLogoDrop,
		onLogoDragEnd,
		officeRows: computed(() => (draft.value.offices || []).map((office, index) => ({ ...office, index }))),
		canAddOffice: computed(() => (draft.value.offices || []).length < MAX_OFFICES),
		officeDialogOpen,
		officeIndex,
		officeForm,
		officeError,
		openOffice,
		saveOffice,
		removeOffice,
		reviews,
		averageRating,
		reviewCount: computed(() => (reviews.value.length === 1 ? "1 review" : `${reviews.value.length} reviews`)),
		shownReviews,
		showAllReviews,
		hasMoreReviews: computed(() => reviews.value.length > REVIEWS_SHOWN),
		storyMenu,
		submitStory: () => openInNewTab(SUBMIT_STORY_URL),
		// editing in place
		draft,
		counter: (path) => limitCounter(draft.value, path),
		isOver: (path) => isOverLimit(draft.value, path),
		uploading,
		uploadLabel,
		logoMenu: computed(() => [
			{ label: uploadLabel("logo_icon", "mark", draft.value.logo_icon), onClick: () => upload("logo_icon", (url) => (draft.value.logo_icon = url)) },
			{ label: uploadLabel("logo", "logo", draft.value.logo), onClick: () => upload("logo", (url) => (draft.value.logo = url)) },
		]),
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
		migrationOptions: computed(() => toOptions(options.value.migrations)),
	}
}
