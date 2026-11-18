// The New project / Edit draft dialog: three steps (name and go-live, how they operate
// today, what they're trying to fix), saved as a Customer Project with the verdict
// recommend() gives. A new project has a fourth, the brief (budget and what to build),
// and is shared with every matching partner straight from the dialog. Shared by the Projects page and both recommendation pages, which
// spread this into their setup() return and render the same dialog blocks. Opened for a
// partner (their Connect button, see partnerConnect.ts), it sends the project to them instead.

import { computed, ref } from "vue"
import {
	BUDGET_OPTIONS,
	GO_LIVE_OPTIONS,
	OPERATION_OPTIONS,
	PROBLEM_OPTIONS,
	STARTER_PACKS_ENABLED,
	SYSTEM_OPTIONS,
	recommend,
} from "@app/utils/recommendation"

function blankProject() {
	return { project_name: "", go_live: "", operations: "", systems: [], problems: [], budget: "", description: "" }
}

// Same rule as the Find Partners wizard: anyone not on spreadsheets has systems to name.
export function usesOtherSystems(value) {
	return !!value && value !== "spreadsheets"
}

// Shared, Hiring, Hired and Completed are all past the draft: the brief has gone out.
export function isProjectSent(status) {
	return ["Shared", "Hiring", "Hired", "Completed"].includes(status)
}

// Where a project opens: a paid order its implementation steps, a sent project the custom
// page (its chats and quotes), a draft whichever page its answers recommended.
export function projectPath(row) {
	if (row.kind === "order") return { path: "/starter-pack-implementation", query: { order: row.order } }
	const custom = !STARTER_PACKS_ENABLED || row.verdict === "custom" || isProjectSent(row.status)
	const path = custom ? "/custom-implementation" : "/starter-pack-recommendation"
	return { path, query: { project: row.project } }
}

// onSaved(project, thread) runs after a successful save, with the saved Customer Project and,
// when it was sent to a partner, the chat it went to.
export function projectDialog(context, { onSaved }) {
	const { call, toast } = context

	const projectDialogOpen = ref(false)
	const newProjectStep = ref(1)
	const newProject = ref(blankProject())
	// Set while editing an existing draft; empty for a new project.
	const editingProject = ref("")
	// The partner a new project goes to, as { name, partner_name }; null for a draft.
	const forPartner = ref(null)
	const savingProject = ref(false)
	// A new project's draft once saved, so retrying a failed share doesn't save a second one.
	const savedDraftName = ref("")
	const briefErrors = ref({ budget: "", description: "", share: "" })

	// Editing a draft or sending to one partner stops at the answers; the brief is asked elsewhere.
	const hasBriefStep = computed(() => !editingProject.value && !forPartner.value)
	const dialogSteps = computed(() => (hasBriefStep.value ? 4 : 3))

	const partnerLabel = computed(() => forPartner.value && (forPartner.value.partner_name || forPartner.value.name))
	const projectDialogTitle = computed(() => {
		if (editingProject.value) return "Edit draft"
		return partnerLabel.value ? `New project for ${partnerLabel.value}` : "New project"
	})
	const projectSaveLabel = computed(() => {
		if (hasBriefStep.value) return "Continue"
		return partnerLabel.value ? `Send to ${partnerLabel.value}` : "Save draft"
	})

	function openNewProject(partner = null) {
		newProject.value = blankProject()
		editingProject.value = ""
		forPartner.value = partner
		savedDraftName.value = ""
		briefErrors.value = { budget: "", description: "", share: "" }
		newProjectStep.value = 1
		projectDialogOpen.value = true
	}

	function editProject(project) {
		newProject.value = {
			project_name: project.project_name || "",
			go_live: project.go_live || "",
			operations: project.operations || "",
			systems: project.systems || [],
			problems: project.problems || [],
			budget: project.budget || "",
			description: project.description || "",
		}
		editingProject.value = project.name
		forPartner.value = null
		newProjectStep.value = 1
		projectDialogOpen.value = true
	}

	function stepFilled(step) {
		return newProjectStep.value >= step
	}

	function nextProjectStep() {
		if (newProjectStep.value === 1 && !newProject.value.project_name.trim()) {
			toast.error("Give the project a name.")
			return
		}
		newProjectStep.value = Math.min(newProjectStep.value + 1, dialogSteps.value)
	}

	function prevProjectStep() {
		newProjectStep.value = Math.max(newProjectStep.value - 1, 1)
	}

	function hasProblem(value) {
		return newProject.value.problems.includes(value)
	}

	function toggleProblem(value) {
		const problems = newProject.value.problems
		newProject.value.problems = problems.includes(value)
			? problems.filter((p) => p !== value)
			: [...problems, value]
	}

	// Step 3's button: on to the brief for a new project, otherwise save as before.
	function finishAnswers() {
		if (hasBriefStep.value) nextProjectStep()
		else saveProjectDraft()
	}

	function projectAnswers() {
		const draft = newProject.value
		const { verdict } = recommend({
			go_live: draft.go_live,
			operations: draft.operations,
			systems: draft.systems,
			problems: draft.problems,
		})
		return {
			project_name: draft.project_name,
			go_live: draft.go_live,
			operations: draft.operations,
			// a spreadsheet shop's earlier pick isn't a system they use
			systems: JSON.stringify(usesOtherSystems(draft.operations) ? draft.systems : []),
			problems: JSON.stringify(draft.problems),
			verdict,
		}
	}

	function saveProjectDraft() {
		if (savingProject.value) return
		const answers = projectAnswers()
		const partner = forPartner.value
		savingProject.value = true
		const saving = partner
			? call("connect.api.projects.start_project_with_partner", { partner: partner.name, ...answers })
			: call("connect.api.projects.save_project", { ...answers, name: editingProject.value || undefined })
		saving
			.then((result) => {
				projectDialogOpen.value = false
				if (partner) onSaved(result.project, result.thread)
				else onSaved(result)
			})
			.catch((error) => {
				const fallback = partner ? "Couldn't send the project. Try again." : "Couldn't save the project. Try again."
				toast.error(error?.messages?.[0] || fallback)
			})
			.finally(() => {
				savingProject.value = false
			})
	}

	function checkBrief() {
		const draft = newProject.value
		briefErrors.value = {
			budget: draft.budget ? "" : "Pick a budget range.",
			description: draft.description.trim() ? "" : "Tell partners what you want built.",
			share: "",
		}
		return !briefErrors.value.budget && !briefErrors.value.description
	}

	// Saves the draft, then sends the brief to every matching partner; the page it opens is the
	// project's quotes. A failed share keeps the dialog open, with the reason, to try again.
	function shareNewProject() {
		if (savingProject.value || !checkBrief()) return
		const draft = newProject.value
		savingProject.value = true
		call("connect.api.projects.save_project", { ...projectAnswers(), name: savedDraftName.value || undefined })
			.then((saved) => {
				savedDraftName.value = saved.name
				return call("connect.api.projects.share_requirements", {
					name: saved.name,
					budget: draft.budget,
					description: draft.description.trim(),
				})
			})
			.then((shared) => {
				projectDialogOpen.value = false
				const count = shared.shared_count || 0
				toast.success(`Sent to ${count} partner${count === 1 ? "" : "s"}. Their quotes arrive here and in Messages.`)
				onSaved(shared)
			})
			.catch((error) => {
				briefErrors.value = { ...briefErrors.value, share: error?.messages?.[0] || "Couldn't share your requirements. Try again." }
			})
			.finally(() => {
				savingProject.value = false
			})
	}

	return {
		projectDialogOpen,
		projectDialogTitle,
		projectSaveLabel,
		newProjectStep,
		newProject,
		savingProject,
		goLiveOptions: GO_LIVE_OPTIONS,
		operationOptions: OPERATION_OPTIONS,
		systemOptions: SYSTEM_OPTIONS,
		problemOptions: PROBLEM_OPTIONS,
		usesOtherSystems,
		openNewProject,
		editProject,
		stepFilled,
		nextProjectStep,
		prevProjectStep,
		hasProblem,
		toggleProblem,
		saveProjectDraft,
		finishAnswers,
		hasBriefStep,
		briefErrors,
		budgetOptions: BUDGET_OPTIONS,
		shareNewProject,
	}
}
