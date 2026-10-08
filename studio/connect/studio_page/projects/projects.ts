// The customer's projects: draft projects (a Customer Project, made from the New project
// dialog) and paid Starter Packs (a Starter Pack Order), newest first, from
// connect.api.projects.list_projects. A paid one opens its implementation steps; a draft
// opens whichever page its answers recommended.

import { computed } from "vue"
import { projectDialog, projectPath } from "@app/utils/projectDialog"

export default function setup(context) {
	const { route, router, call, toast, myProjects } = context

	// The repeater needs one key across both kinds of row.
	const projects = computed(() =>
		(myProjects?.data || []).map((row) => ({ ...row, key: row.order || row.project })),
	)

	const projectCount = computed(() => {
		const count = projects.value.length
		return `${count} project${count === 1 ? "" : "s"}, newest first`
	})

	function openProject(row) {
		if (row) router.push(projectPath(row))
	}

	// The list only ever shows a date, so recent ones read better as words.
	function projectDate(value) {
		if (!value) return ""
		const at = new Date(value)
		const today = new Date()
		if (at.toDateString() === today.toDateString()) return "Today"
		const yesterday = new Date(today)
		yesterday.setDate(today.getDate() - 1)
		if (at.toDateString() === yesterday.toDateString()) return "Yesterday"
		const options = { month: "short", day: "numeric" }
		if (at.getFullYear() !== today.getFullYear()) options.year = "numeric"
		return at.toLocaleDateString("en-US", options)
	}

	// A saved draft opens on whichever page its answers recommended.
	const dialog = projectDialog(context, {
		onSaved: (project) => router.push(projectPath({ kind: "project", project: project.name, verdict: project.verdict })),
	})

	// Older links sent "Change my answers" here as /projects?edit=CP-…; still honoured.
	if (route.query.edit) {
		call("connect.api.projects.get_project", { name: String(route.query.edit) })
			.then((project) => dialog.editProject(project))
			.catch(() => toast.error("Couldn't open that project."))
		router.replace({ path: route.path })
	}

	return {
		...dialog,
		projects,
		projectCount,
		openProject,
		projectDate,
	}
}
