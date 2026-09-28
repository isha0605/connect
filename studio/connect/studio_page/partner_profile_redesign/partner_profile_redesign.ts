// Partner profile: a Connect button in the pinned header once the one beside the partner's
// name has scrolled away, and the partner's story at the end of the page.

import { computed, onScopeDispose } from "vue"

const HERO_CONNECT = "contact-btn-ppr"
const HEADER = "header-row-ppr"
// How long to keep looking for the page's buttons after it opens.
const WAIT_FOR_PAGE_MS = 5000

function article(word) {
	return /^[aeiou]/i.test(word) ? "an" : "a"
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

	return { connect, origin }
}
