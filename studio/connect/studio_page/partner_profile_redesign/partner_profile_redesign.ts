// Partner profile: the sections the partner's Listing shows (the partnerprofilesections and
// partnerprofilestories components, fed by useProfileView), reviews, a Connect button in the pinned
// header once the one beside the partner's name has scrolled away, and a lightbox for the photos.
// Connect opens the New project dialog for this partner (partnerConnect.ts).

import { computed, onScopeDispose, ref, watch } from "vue"
import { partnerConnect } from "@app/utils/partnerConnect"
import { viewerCurrency } from "@app/utils/money"
import { useProfileView } from "@app/utils/profileView"
import { onPreviewChange, readPreview, withPreview } from "@app/utils/profilePreview"
import { goToSignIn } from "@app/utils/signIn"
import { startTracking } from "@app/utils/tracking"

const HERO_CONNECT = "contact-btn-ppr"
const HEADER = "header-row-ppr"
// How long to keep looking for the page's buttons after it opens.
const WAIT_FOR_PAGE_MS = 5000

function escapeAttr(value) {
	return String(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;")
}

// The Partner record in the shape the shared sections read, the same as get_my_profile's.
function profileOf(record) {
	if (!record) return null
	return {
		...record,
		apps: (record.apps || []).map((row) => row.app),
		migrations: (record.migrations || []).map((row) => row.migration_path),
		founder: (record.team || []).find((member) => member.is_founder) || {},
	}
}

export default function setup(context) {
	startTracking(context)
	const { route, partner, showHeaderConnect, selectedStoryIndustry, toast } = context

	// Reviews: only the partner's real customers write one (hired on Connect, or asked by the
	// partner). ?review=1, from a review request the customer just confirmed, opens the form until
	// they have reviewed, so going Back to it or reloading doesn't open it again.
	const { call, reviewDialogOpen, reviewRating, reviewHeadline, reviewQuote } = context
	async function openReview({ fromLink = false } = {}) {
		if (window.is_guest) {
			goToSignIn()
			return
		}
		try {
			const { review, can_review, reviewed_by_teammate } = await call("connect.api.partner.get_my_review_for_partner", {
				partner: route.params.partner_id,
			})
			if (fromLink && review) return
			if (!can_review) {
				toast.info(
					reviewed_by_teammate
						? "Someone at your company has already reviewed this partner."
						: "Only customers who completed a project with this partner on Connect, or whom they asked for feedback, can review them.",
				)
				return
			}
			reviewRating.value = review ? review.rating : 0
			reviewHeadline.value = review ? review.headline || "" : ""
			reviewQuote.value = review ? review.quote || "" : ""
			reviewDialogOpen.value = true
		} catch {
			toast.error("Couldn't open the review form. Try again.")
		}
	}
	if (route.query.review && !window.is_guest) openReview({ fromLink: true })

	// ?preview=1, from the partner's own Profile builder: their unsaved profile over the saved
	// one, kept in step as they type in the builder's tab. Only ever this browser's own draft.
	const partnerId = route.params.partner_id
	let savedRecord = null
	function showPreview(draft) {
		if (draft && savedRecord) partner.setData(withPreview(savedRecord, draft))
	}
	if (route.query.preview) {
		const stopWatching = watch(
			() => partner.data,
			(data) => {
				if (!data || savedRecord) return
				savedRecord = data
				showPreview(readPreview(partnerId))
				toast.info("Preview: your unsaved changes. Customers see the saved profile.")
			},
			{ immediate: true },
		)
		const stopListening = onPreviewChange(partnerId, showPreview)
		onScopeDispose(() => {
			stopWatching()
			stopListening()
		})
	}

	// Both Connects on the page: the one beside the partner's name and the header's.
	const connecting = partnerConnect(context)
	function connect() {
		connecting.connectWith({ name: route.params.partner_id, company_name: partner.data?.company_name })
	}

	// Watch the hero's Connect button against the area below the header: when it has
	// scrolled under the header, the header's own Connect appears. The page renders after
	// this runs, so look for the button until it's there.
	let observer = null
	let timer = null
	const startedAt = Date.now()
	function watchHeroConnect() {
		const button = document.querySelector(`[data-component-id="${HERO_CONNECT}"]`)
		const header = document.querySelector(`[data-component-id="${HEADER}"]`)
		if (!button || !header) {
			if (Date.now() - startedAt < WAIT_FOR_PAGE_MS) timer = setTimeout(watchHeroConnect, 100)
			return
		}
		observer = new IntersectionObserver(
			([entry]) => {
				showHeaderConnect.value = !entry.isIntersecting
			},
			{ rootMargin: `-${header.offsetHeight}px 0px 0px 0px` },
		)
		observer.observe(button)
	}
	watchHeroConnect()
	onScopeDispose(() => {
		clearTimeout(timer)
		observer?.disconnect()
	})

	// The sections are the Listing's, never in edit mode here.
	const isEditing = ref(false)
	const profile = computed(() => profileOf(partner.data))
	const stories = computed(() => partner.data?.success_stories || [])
	const customerCurrency = computed(() => viewerCurrency(context.myContext?.data))
	const view = useProfileView({ profile, stories, isEditing, selectedStoryIndustry, forCustomers: true, viewerCurrency: customerCurrency })

	// Each Partner Photo is an image, or a video with the image as its cover. Kept in the
	// photos' own order, so a tile's index is its place in the lightbox.
	const galleryItems = computed(() =>
		(partner.data?.photos || []).map((photo) => ({ image: photo.image || "", video: photo.video || "" })),
	)

	// -1 while the lightbox is closed.
	const galleryIndex = ref(-1)
	const galleryOpen = computed(() => galleryIndex.value >= 0)
	const galleryCounter = computed(() => `${galleryIndex.value + 1} / ${galleryItems.value.length}`)

	function openGallery(index) {
		if (galleryItems.value[index]) galleryIndex.value = index
	}

	function closeGallery() {
		galleryIndex.value = -1
	}

	function showPrevious() {
		const count = galleryItems.value.length
		galleryIndex.value = (galleryIndex.value - 1 + count) % count
	}

	function showNext() {
		galleryIndex.value = (galleryIndex.value + 1) % galleryItems.value.length
	}

	// Rebuilt for each item, so moving on from a video stops it.
	const lightboxMedia = computed(() => {
		const item = galleryItems.value[galleryIndex.value]
		if (!item) return ""
		const fit = "max-width:100%;max-height:100%;border-radius:12px;display:block;"
		if (item.video) {
			const poster = item.image ? ` poster="${escapeAttr(item.image)}"` : ""
			return `<video src="${escapeAttr(item.video)}"${poster} controls autoplay playsinline style="${fit}"></video>`
		}
		return `<img src="${escapeAttr(item.image)}" alt="" style="${fit}object-fit:contain;">`
	})

	function onGalleryKey(event) {
		if (event.key === "Escape") closeGallery()
		else if (event.key === "ArrowLeft") showPrevious()
		else if (event.key === "ArrowRight") showNext()
	}
	watch(galleryOpen, (open) => {
		if (open) window.addEventListener("keydown", onGalleryKey)
		else window.removeEventListener("keydown", onGalleryKey)
	})
	onScopeDispose(() => window.removeEventListener("keydown", onGalleryKey))

	return {
		...connecting,
		...view,
		isEditing,
		profile,
		connect,
		openReview,
		goToSignIn,
		openMedia: (photo) => openGallery(photo.index),
		galleryItems,
		galleryOpen,
		galleryCounter,
		closeGallery,
		showPrevious,
		showNext,
		lightboxMedia,
	}
}
