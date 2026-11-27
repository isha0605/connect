import { watch } from "vue"
import { startTracking } from "@app/utils/tracking"
import { useMyContext } from "@app/utils/myContext"

// "Get started" is the app's front door for people who aren't signed in. Anyone signed in
// belongs on Home instead — except inside the Studio editor, which has to show this page.

export default function setup(context) {
	startTracking(context)
	const { router } = context
	const myContext = useMyContext()
	const inEditor = window.location.pathname.startsWith("/studio/")

	watch(
		() => myContext.data,
		(data) => {
			if (inEditor || !data || !data.user || data.user === "Guest") return
			router.replace("/home")
		},
		{ immediate: true },
	)

	return { myContext }
}
