// Opens the project questions (studio_components/ProjectQuestionsDialog.vue): a new project
// shared with every partner it matches, or, given a partner, sent to them. Pages spread this
// into their setup() return and render the ProjectQuestionsDialog block bound to it.

import { ref } from "vue"
import { STARTER_PACKS_ENABLED } from "@app/utils/recommendation"

// The project questions, a step each (Pragati's CompanyQuestions + brief), and what each
// required one says when left unanswered. How they run today (operations, systems, what
// else) is optional. The server (questions.py) refuses a project missing any required one.
export const PROJECT_QUESTION_STEPS = [
	["country", "company_size", "industries"],
	["operations", "systems", "other_system"],
	["problems"],
	["budget", "apps", "description"],
]
export const MISSING_ANSWERS = {
	country: "Pick where your business is based.",
	company_size: "Pick the number of employees.",
	industries: "Pick your industry.",
	problems: "Pick what you are trying to fix.",
	budget: "Pick a budget range.",
	apps: "Pick the apps you need.",
	description: "Tell partners what you need.",
}
// The system that asks "What else do you use?".
export const OTHER_SYSTEM = "Something else"

// { field: message } for each required one of `fields` that `answers` leaves unanswered.
export function missingAnswers(answers, fields = Object.keys(MISSING_ANSWERS)) {
	const found = {}
	for (const field of fields) {
		if (!MISSING_ANSWERS[field]) continue
		const value = answers[field]
		const empty = Array.isArray(value) ? !value.length : !String(value || "").trim()
		if (empty) found[field] = MISSING_ANSWERS[field]
	}
	return found
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
