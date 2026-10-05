// Partner profile: a Connect button in the pinned header once the one beside the partner's
// name has scrolled away, the photo and video gallery, and the partner's story at the end of
// the page.

import { computed, onScopeDispose, ref, watch } from "vue"

const HERO_CONNECT = "contact-btn-ppr"
const HEADER = "header-row-ppr"
// How long to keep looking for the page's buttons after it opens.
const WAIT_FOR_PAGE_MS = 5000

function article(word) {
	return /^[aeiou]/i.test(word) ? "an" : "a"
}

const PMM_GUIDE = "https://frappe.io/partners/maturity-model"

// The grid shows three tiles; the third says how many more the gallery holds.
const GALLERY_TILES = 3

function escapeAttr(value) {
	return String(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;")
}

function listOf(items, shown = 3) {
	const lead = items.slice(0, shown)
	const rest = items.length - lead.length
	if (rest > 0) return `${lead.join(", ")} and ${rest} more`
	if (lead.length <= 1) return lead[0] || ""
	return `${lead.slice(0, -1).join(", ")} and ${lead.at(-1)}`
}

export default function setup(context) {
	const { partner, myContext, showHeaderConnect, loginDialogOpen, contactStep, contactDialogOpen } = context

	// Same as the Connect button beside the partner's name.
	function connect() {
		if (!myContext.data || !myContext.data.customer) {
			loginDialogOpen.value = true
		} else {
			contactStep.value = 1
			contactDialogOpen.value = true
		}
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

	// ---- Process maturity (PMM) ----
	// Frappe rates partners Level 1 to 5; 0 means not rated yet (frappe.io shows TBD).
	const pmmLevel = computed(() => Math.round(Number(partner.data?.pmm_level) || 0))
	const pmmLabel = computed(() => (pmmLevel.value ? String(pmmLevel.value) : "Not rated yet"))

	function openPmmGuide() {
		window.open(PMM_GUIDE, "_blank", "noopener")
	}

	// ---- Gallery ----
	// Each Partner Photo is an image, or a video with the image as its cover.
	const galleryItems = computed(() =>
		(partner.data?.photos || [])
			.filter((p) => p.image || p.video)
			.map((p) => ({ image: p.image || "", video: p.video || "" })),
	)
	const moreCount = computed(() => Math.max(0, galleryItems.value.length - GALLERY_TILES))

	function tileBackground(index) {
		const item = galleryItems.value[index]
		return item?.image ? `url("${item.image}")` : "none"
	}

	function isVideo(index) {
		return !!galleryItems.value[index]?.video
	}

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

	// The partner's own account of how they started when they've written one, else the
	// Description they gave Frappe, else a line made only from facts on their record —
	// nothing about their history is made up.
	const origin = computed(() => {
		const p = partner.data
		if (!p) return null
		const place = [p.city, p.country].filter(Boolean).join(", ")
		const eyebrow = p.year_founded
			? `Founded ${p.year_founded}${place ? ` in ${place}` : ""}`
			: place
				? `Based in ${place}`
				: ""
		const text = String(p.origin_story || p.description || "").trim()
		const paragraphs = text
			? text
					.split(/\n\s*\n/)
					.map((part) => part.replace(/\s*\n\s*/g, " ").trim())
					.filter(Boolean)
			: [factsAbout(p, place)]
		return {
			eyebrow,
			heading: p.origin_story ? "How they got started" : `About ${p.partner_name}`,
			paragraphs,
		}
	})

	function factsAbout(p, place) {
		const tier = p.tier ? `${article(p.tier)} ${p.tier} Frappe partner` : "a Frappe partner"
		let line = `${p.partner_name} is ${tier}${place ? ` based in ${place}` : ""}.`
		const stories = p.success_stories || []
		if (stories.length) {
			const industries = [...new Set(stories.map((s) => s.category).filter(Boolean))]
			const count = `${stories.length} success ${stories.length === 1 ? "story" : "stories"}`
			line += ` They have published ${count}${industries.length ? ` across ${listOf(industries)}` : ""}.`
		}
		return line
	}

	return {
		connect,
		origin,
		pmmLevel,
		pmmLabel,
		openPmmGuide,
		galleryItems,
		moreCount,
		tileBackground,
		isVideo,
		galleryOpen,
		galleryCounter,
		openGallery,
		closeGallery,
		showPrevious,
		showNext,
		lightboxMedia,
	}
}
