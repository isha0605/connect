import { toTime } from "@app/utils/partnerRecords"

// Filters a list's Filter button builds (studio_components/ListFilter.vue), applied by the page to
// the rows it already has. A field is { fieldname, label, type: "text" | "select" | "date", options };
// a filter is { fieldname, operator, value }.

const option = (value) => ({ label: value, value })
const SET_OPERATORS = ["is set", "is not set"]

export const OPERATORS = {
	text: ["like", "not like", "equals", "not equals", ...SET_OPERATORS].map(option),
	select: ["equals", "not equals", ...SET_OPERATORS].map(option),
	date: ["after", "before"].map(option),
}

export const needsValue = (operator) => !SET_OPERATORS.includes(operator)

export function newFilter(field) {
	return { fieldname: field.fieldname, operator: OPERATORS[field.type][0].value, value: "" }
}

// values: the row's value for each fieldname. A filter still waiting for its value narrows nothing.
export function matchesFilters(values, filters) {
	return filters.every((filter) => matchesFilter(values[filter.fieldname], filter))
}

function matchesFilter(value, { operator, value: wanted }) {
	if (needsValue(operator) && (wanted === "" || wanted == null)) return true
	return TESTS[operator](value, wanted)
}

const lower = (value) => String(value ?? "").toLowerCase()
const DAY_MS = 24 * 60 * 60 * 1000
// A picked date ("2026-11-03") as the start of that day in the viewer's own timezone.
const dayStart = (date) => new Date(`${date}T00:00:00`).getTime()

const TESTS = {
	"is set": (value) => Boolean(value),
	"is not set": (value) => !value,
	like: (value, wanted) => lower(value).includes(lower(wanted)),
	"not like": (value, wanted) => !lower(value).includes(lower(wanted)),
	equals: (value, wanted) => lower(value) === lower(wanted),
	"not equals": (value, wanted) => lower(value) !== lower(wanted),
	// a date value is a timestamp string, like a lead's last_message_at
	after: (value, wanted) => toTime(value) >= dayStart(wanted) + DAY_MS,
	before: (value, wanted) => toTime(value) < dayStart(wanted),
}
