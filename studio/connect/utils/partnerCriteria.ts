// Who a brief goes to: the criteria summary ("Based in India", "All tiers", …) and the Edit
// criteria chips, shared by the custom implementation page and the Contact partners flow on
// find-partners-redesign.
//
// Countries and industries come from the questions; the chips narrow within them by city,
// tier and how they want to work (connect.api.projects.partner_criteria counts each chip).
// The go-live chip edits the project's own answer — it isn't a partner filter.

import { computed, ref } from "vue"
import { GO_LIVE_CRITERIA, goLiveCriterion } from "@app/utils/recommendation"

const CHIP_GROUPS = ["cities", "tiers", "work"]

export function blankCriteria() {
	return { countries: [], industries: [], cities: [], tiers: [], work: [] }
}

export function orList(values, suffix = "") {
	if (values.length <= 1) return values.join("") + suffix
	return `${values.slice(0, -1).join(", ")} or ${values[values.length - 1]}${suffix}`
}

export function workCriterion(work) {
	if (work.length === 1 && work[0] === "onsite") return "On premises"
	if (work.length === 1 && work[0] === "remote") return "Remote"
	return "Remote or on premises"
}

// The summary list, as { icon, label } rows.
export function criteriaSummary(criteria, goLive) {
	const c = { ...blankCriteria(), ...(criteria || {}) }
	const place = c.cities.length ? c.cities : c.countries
	return [
		{ icon: "lucide-map-pin", label: place.length ? `Based in ${orList(place)}` : "Based in any region" },
		{
			icon: "lucide-building-2",
			label: c.industries.length
				? `Offer services for ${orList(c.industries)}`
				: "Offer services for any industry",
		},
		{ icon: "lucide-calendar", label: goLiveCriterion(goLive) },
		{ icon: "lucide-award", label: c.tiers.length ? orList(c.tiers, " tier") : "All tiers" },
		{ icon: "lucide-users", label: workCriterion(c.work) },
	]
}

// The Edit criteria chips over a draft copy of `saved()`. `saved` and `goLive` are getters
// for what the page holds now; nothing changes there until the page takes `draft` back.
export function partnerCriteria(context, { saved, goLive }) {
	const { call } = context

	const facets = ref({ cities: [], tiers: [], work: [], total: null })
	const draft = ref({ ...blankCriteria(), go_live: "" })

	function filtersOf(value) {
		const { go_live, ...filters } = value
		return filters
	}

	function loadFacets() {
		call("connect.api.projects.partner_criteria", { criteria: JSON.stringify(filtersOf(draft.value)) })
			.then((data) => {
				facets.value = data
			})
			.catch(() => {})
	}

	// Starts the chips from what's saved, keeping the countries and industries the chips
	// don't show.
	function startEditing() {
		const c = { ...blankCriteria(), ...(saved() || {}) }
		draft.value = {
			...c,
			cities: [...c.cities],
			tiers: [...c.tiers],
			work: [...c.work],
			go_live: goLive() || "",
		}
		loadFacets()
	}

	function toggleCriterion(group, value) {
		const list = draft.value[group]
		draft.value[group] = list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
		loadFacets()
	}

	function setGoLive(value) {
		draft.value.go_live = value
	}

	// Clear lifts the chip filters; countries, industries and go-live are answers, so they stay.
	function clearCriteria() {
		const cleared = { ...draft.value }
		for (const group of CHIP_GROUPS) cleared[group] = []
		draft.value = cleared
		loadFacets()
	}

	// Each chip group as { value, label, count, picked } for the dialog's repeaters.
	const chip = (group) => (item) => ({
		value: item.value,
		label: item.label || item.value,
		count: item.count,
		picked: draft.value[group].includes(item.value),
	})
	const cityChips = computed(() => facets.value.cities.map(chip("cities")))
	const tierChips = computed(() => facets.value.tiers.map(chip("tiers")))
	const workChips = computed(() => facets.value.work.map(chip("work")))
	const goLiveChips = computed(() =>
		GO_LIVE_CRITERIA.map((o) => ({ ...o, picked: draft.value.go_live === o.value })),
	)

	const partnersLeft = computed(() => {
		const n = facets.value.total
		if (n === null || n === undefined) return ""
		return `${n} partner${n === 1 ? "" : "s"} left.`
	})

	return {
		criteriaDraft: draft,
		criteriaFacets: facets,
		draftFilters: () => filtersOf(draft.value),
		startEditing,
		toggleCriterion,
		setGoLive,
		clearCriteria,
		cityChips,
		tierChips,
		workChips,
		goLiveChips,
		partnersLeft,
	}
}
