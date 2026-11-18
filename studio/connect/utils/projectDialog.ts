// Opens the project questions (studio_components/ProjectQuestionsDialog.vue): a new project
// shared with every partner it matches, or, given a partner, sent to them. Pages spread this
// into their setup() return and render the ProjectQuestionsDialog block bound to it.

import { ref } from "vue"
import { STARTER_PACKS_ENABLED, WORK_OPTIONS } from "@app/utils/recommendation"

// The project questions, a step each, and what each says when left unanswered. The server
// (questions.py) refuses a project missing any of them, with the same words.
export const PROJECT_QUESTION_STEPS = [
	["regions", "company_size", "industries"],
	["apps", "go_live", "work_modes"],
	["operations", "systems", "problems"],
	["budget", "description"],
]
export const MISSING_ANSWERS = {
	regions: "Pick where your partners should be from.",
	company_size: "Pick the number of employees.",
	industries: "Pick your industry.",
	apps: "Pick the apps you need.",
	go_live: "Pick when you need it live.",
	work_modes: "Pick how you want to work.",
	operations: "Pick how you run your operations today.",
	systems: "Pick the systems you use.",
	problems: "Pick what you are trying to solve.",
	budget: "Pick a budget range.",
	description: "Tell partners what you need.",
}

// { field: message } for each of `fields` that `answers` leaves unanswered.
export function missingAnswers(answers, fields = Object.keys(MISSING_ANSWERS)) {
	const found = {}
	for (const field of fields) {
		if (field === "systems" && !usesOtherSystems(answers.operations)) continue
		const value = answers[field]
		const empty = Array.isArray(value) ? !value.length : !String(value || "").trim()
		if (empty) found[field] = MISSING_ANSWERS[field]
	}
	return found
}

// "How do you want to work?" is one choice, kept as the work modes it allows: either is both.
export const WORK_CHOICES = [...WORK_OPTIONS, { label: "Either works", value: "either" }]

export function workChoiceOf(modes) {
	return (modes || []).length > 1 ? "either" : (modes || [])[0] || ""
}

export function workModesOf(choice) {
	if (choice === "either") return WORK_OPTIONS.map((option) => option.value)
	return choice ? [choice] : []
}

// Same rule as the Find Partners wizard: anyone not on spreadsheets has systems to name.
export function usesOtherSystems(value) {
	return !!value && value !== "spreadsheets"
}

// Shared, Hiring, Hired and Completed are all past the draft: the brief has gone out.
export function isProjectSent(status) {
	return ["Shared", "Hiring", "Hired", "Completed"].includes(status)
}

// Where a project opens: a paid order its implementation steps, a project the custom page
// (its chats and quotes).
export function projectPath(row) {
	if (row.kind === "order") return { path: "/starter-pack-implementation", query: { order: row.order } }
	const custom = !STARTER_PACKS_ENABLED || row.verdict === "custom" || isProjectSent(row.status)
	const path = custom ? "/custom-implementation" : "/starter-pack-recommendation"
	return { path, query: { project: row.project } }
}

export function projectDialog() {
	const projectDialogOpen = ref(false)
	// { name, partner_name } the project goes to; null shares it with every match.
	const projectDialogPartner = ref(null)
	// One of the customer's projects to send to that partner, with its missing answers asked.
	const projectDialogProject = ref(null)

	function openNewProject(partner = null, project = null) {
		projectDialogPartner.value = partner
		projectDialogProject.value = project
		projectDialogOpen.value = true
	}

	return { projectDialogOpen, projectDialogPartner, projectDialogProject, openNewProject }
}
