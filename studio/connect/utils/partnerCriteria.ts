// Who a brief goes to: the criteria summary ("Based in India", "All tiers", …) and the Edit
// criteria chips, for the Contact partners flow on find-partners-redesign.
//
// The country and industries come from the questions; the chips narrow within them by city
// and tier (connect.api.projects.partner_criteria counts each chip).

import { computed, ref } from "vue"

const CHIP_GROUPS = ["cities", "tiers"]

export function blankCriteria() {
	return { countries: [], industries: [], apps: [], cities: [], tiers: [] }
}

export function orList(values, suffix = "") {
	if (values.length <= 1) return values.join("") + suffix
	return `${values.slice(0, -1).join(", ")} or ${values[values.length - 1]}${suffix}`
}

// The summary list, as { icon, label } rows.
export function criteriaSummary(criteria) {
	const c = { ...blankCriteria(), ...(criteria || {}) }
	const place = c.cities.length ? c.cities : c.countries
	return [
		{ icon: "lucide-map-pin", label: place.length ? `Based in ${orList(place)}` : "Based anywhere" },
		{
			icon: "lucide-building-2",
			label: c.industries.length
				? `Offer services for ${orList(c.industries)}`
				: "Offer services for any industry",
		},
		{ icon: "lucide-award", label: c.tiers.length ? orList(c.tiers, " tier") : "All tiers" },
	]
}

// The Edit criteria chips over a draft copy of `saved()`, a getter for what the page holds
// now; nothing changes there until the page takes `draftFilters()` back.
export function partnerCriteria(context, { saved }) {
	const { call } = context

	const facets = ref({ cities: [], tiers: [], total: null })
	const draft = ref(blankCriteria())

	function loadFacets() {
		call("connect.api.projects.partner_criteria", { criteria: JSON.stringify(draft.value) })
			.then((data) => {
				facets.value = data
			})
			.catch(() => {})
	}

	// Starts the chips from what's saved, keeping the answers the chips don't show.
	function startEditing() {
		const c = { ...blankCriteria(), ...(saved() || {}) }
		draft.value = { ...c, cities: [...c.cities], tiers: [...c.tiers] }
		loadFacets()
	}

	function toggleCriterion(group, value) {
		const list = draft.value[group]
		draft.value[group] = list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
		loadFacets()
	}

	// Clear lifts the chip filters; the answers stay.
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

	const partnersLeft = computed(() => {
		const n = facets.value.total
		if (n === null || n === undefined) return ""
		return `${n} partner${n === 1 ? "" : "s"} left.`
	})

	return {
		criteriaDraft: draft,
		criteriaFacets: facets,
		draftFilters: () => ({ ...draft.value }),
		startEditing,
		toggleCriterion,
		clearCriteria,
		cityChips,
		tierChips,
		partnersLeft,
	}
}
