import { watch } from "vue"
import { projectDialog } from "@app/utils/projectDialog"
import { startTracking } from "@app/utils/tracking"

// "Get started" is the app's front door for people who aren't signed in. Anyone signed in
// belongs on Home instead — except inside the Studio editor, which has to show this page.
// Contact partners opens the project questions; a guest signs up to send them (see
// ProjectQuestionsDialog.vue).

export default function setup(context) {
	startTracking(context)
	const { router, myContext } = context
	const inEditor = window.location.pathname.startsWith("/studio/")

	watch(
		() => myContext?.data,
		(data) => {
			if (inEditor || !data || !data.user || data.user === "Guest") return
			router.replace("/home")
		},
		{ immediate: true },
	)

	return { ...projectDialog() }
}
