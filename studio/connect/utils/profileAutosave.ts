// Saves the Listing's draft as the partner edits it, to their unpublished changes: a second after
// they stop typing, one save at a time. A draft that breaks a limit isn't sent, since the server
// would refuse all of it; the field shows why. Publish still decides when businesses see it.

import { computed, ref, watch } from "vue"
import { PROFILE_API, draftProblem, toDraft, toSavePayload } from "@app/utils/partnerProfile"

const SAVE_DELAY_MS = 1000

export function useProfileAutosave({ call, draft, profile, uploading, onSaved }) {
	// idle | waiting | saving | saved | blocked (a field breaks a limit) | failed
	const state = ref("idle")
	const error = ref("")
	let savedPayload = ""
	let timer = null
	let queue = Promise.resolve()

	const payloadOf = () => JSON.stringify(toSavePayload(draft.value))
	const isSaved = () => payloadOf() === savedPayload

	// After the draft is (re)loaded from the server: that is what's saved.
	function reset() {
		clearTimeout(timer)
		savedPayload = payloadOf()
		state.value = "idle"
		error.value = ""
	}

	function schedule() {
		clearTimeout(timer)
		timer = setTimeout(flush, SAVE_DELAY_MS)
	}

	watch(
		draft,
		() => {
			if (isSaved()) return
			state.value = "waiting"
			schedule()
		},
		{ deep: true },
	)

	// Saves now, after any save already running. Resolves once the draft is saved or can't be.
	function flush() {
		clearTimeout(timer)
		queue = queue.then(saveNow)
		return queue
	}

	async function saveNow() {
		if (isSaved()) return
		if (uploading.value) return schedule()

		const problem = draftProblem(draft.value, toDraft(profile.value))
		if (problem) {
			state.value = "blocked"
			error.value = problem
			return
		}

		const payload = payloadOf()
		state.value = "saving"
		try {
			await call(`${PROFILE_API}.update_my_partner_profile`, { ...JSON.parse(payload), as_draft: 1 })
			savedPayload = payload
			error.value = ""
			state.value = isSaved() ? "saved" : "waiting"
			await onSaved()
		} catch (failure) {
			state.value = "failed"
			error.value = failure?.messages?.[0] || "Couldn't save your changes. Edit again to retry."
		}
	}

	const status = computed(() => {
		if (state.value === "waiting" || state.value === "saving") return "Saving…"
		if (state.value === "saved") return "Saved"
		return error.value
	})

	return { reset, flush, isSaved, status, hasProblem: computed(() => !!error.value) }
}
