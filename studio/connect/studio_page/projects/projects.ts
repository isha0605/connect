// Projects has no list: it opens the customer's current project (see projectSwitcher.ts),
// whose header switches between them. It only says so itself when there is none to open.

import { ref } from "vue"
import { projectPath } from "@app/utils/projectDialog"
import { currentProject, loadProjects } from "@app/utils/projectSwitcher"
import { startTracking } from "@app/utils/tracking"
import { useMyContext } from "@app/utils/myContext"

export default function setup(context) {
	startTracking(context)
	const { router, call } = context

	// The editor opens pages to design them, so it must not be sent elsewhere.
	const inEditor = window.location.pathname.startsWith("/studio/")
	const noProject = ref(false)
	const loadError = ref(false)

	if (!inEditor) {
		loadProjects(call)
			.then((projects) => {
				const project = currentProject(projects)
				if (project) router.replace(projectPath(project))
				else noProject.value = true
			})
			.catch(() => (loadError.value = true))
	}

	return {
		myContext: useMyContext(),
		noProject,
		loadError,
	}
}
