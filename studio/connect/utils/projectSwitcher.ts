// The customer's projects, one at a time: Projects opens the current one, and its header
// switches between them. A new project can start only once every project is Completed,
// since customers rarely run two at once.

import { computed, ref } from "vue"
import { projectPath } from "@app/utils/projectDialog"

// Newest first, as connect.api.projects.list_projects returns them; Starter Pack orders aside.
export function loadProjects(call) {
	return call("connect.api.projects.list_projects").then((rows) =>
		(rows || []).filter((row) => row.kind === "project"),
	)
}

// The newest project still in progress, else the newest one.
export function currentProject(projects) {
	return projects.find((row) => row.status !== "Completed") || projects[0] || null
}

export function projectSwitcher({ call, router }, openNewProject) {
	const projects = ref([])
	const openProject = ref("")

	function refreshProjects(name) {
		openProject.value = name
		loadProjects(call)
			.then((rows) => (projects.value = rows))
			.catch(() => {})
	}

	const canStartNewProject = computed(
		() => projects.value.length > 0 && projects.value.every((row) => row.status === "Completed"),
	)
	const hasProjectSwitcher = computed(() => projects.value.length > 1)
	const openProjectTitle = computed(
		() => projects.value.find((row) => row.project === openProject.value)?.project_title || "Project",
	)

	const switcherOptions = computed(() => {
		const groups = [{ group: "Projects", options: projects.value.map(switcherItem) }]
		if (canStartNewProject.value) {
			groups.push({ group: "", options: [{ label: "New project", icon: "lucide-plus", onClick: () => openNewProject() }] })
		}
		return groups
	})

	function switcherItem(row) {
		return {
			label: row.project_title,
			selected: row.project === openProject.value,
			onClick: () => row.project !== openProject.value && router.push(projectPath(row)),
		}
	}

	return {
		refreshProjects,
		canStartNewProject,
		hasProjectSwitcher,
		openProjectTitle,
		switcherOptions,
	}
}
