// The New project / Edit draft dialog: three steps (name and go-live, how they operate
// today, what they're trying to fix), saved as a Customer Project with the verdict
// recommend() gives. Shared by the Projects page and both recommendation pages, which
// spread this into their setup() return and render the same dialog blocks.

import { computed, ref } from "vue"
import {
	GO_LIVE_OPTIONS,
	OPERATION_OPTIONS,
	PROBLEM_OPTIONS,
	SYSTEM_OPTIONS,
	recommend,
} from "@app/utils/recommendation"

const DIALOG_STEPS = 3

function blankProject() {
	return { project_name: "", go_live: "", operations: "", systems: [], problems: [] }
}

// Same rule as the Find Partners wizard: anyone not on spreadsheets has systems to name.
export function usesOtherSystems(value) {
	return !!value && value !== "spreadsheets"
}

// Where a project opens: a paid order its implementation steps, a draft whichever
// page its answers recommended.
export function projectPath(row) {
	if (row.kind === "order") return { path: "/starter-pack-implementation", query: { order: row.order } }
	const path = row.verdict === "custom" ? "/custom-implementation" : "/starter-pack-recommendation"
	return { path, query: { project: row.project } }
}

// onSaved(project) runs after a successful save, with the saved Customer Project.
export function projectDialog(context, { onSaved }) {
	const { call, toast } = context

	const projectDialogOpen = ref(false)
	const newProjectStep = ref(1)
	const newProject = ref(blankProject())
	// Set while editing an existing draft; empty for a new project.
	const editingProject = ref("")
	const savingProject = ref(false)

	const projectDialogTitle = computed(() => (editingProject.value ? "Edit draft" : "New project"))

	function openNewProject() {
		newProject.value = blankProject()
		editingProject.value = ""
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
		}
		editingProject.value = project.name
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
		newProjectStep.value = Math.min(newProjectStep.value + 1, DIALOG_STEPS)
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

	function saveProjectDraft() {
		if (savingProject.value) return
		const draft = newProject.value
		const { verdict } = recommend({
			go_live: draft.go_live,
			operations: draft.operations,
			systems: draft.systems,
			problems: draft.problems,
		})
		savingProject.value = true
		call("connect.api.projects.save_project", {
			project_name: draft.project_name,
			go_live: draft.go_live,
			operations: draft.operations,
			// a spreadsheet shop's earlier pick isn't a system they use
			systems: JSON.stringify(usesOtherSystems(draft.operations) ? draft.systems : []),
			problems: JSON.stringify(draft.problems),
			verdict,
			name: editingProject.value || undefined,
		})
			.then((project) => {
				projectDialogOpen.value = false
				onSaved(project)
			})
			.catch((error) => {
				toast.error(error?.messages?.[0] || "Couldn't save the project. Try again.")
			})
			.finally(() => {
				savingProject.value = false
			})
	}

	return {
		projectDialogOpen,
		projectDialogTitle,
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
	}
}
