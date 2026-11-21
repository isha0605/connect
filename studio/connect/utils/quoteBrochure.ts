import { computed, ref } from "vue"
import { useFileUpload } from "frappe-ui"

// What send_quote accepts: a PDF or an image, never an SVG (it could run a script when opened).
const BROCHURE_TYPES = ".pdf,.png,.jpg,.jpeg,.webp,.gif"

function sizeLabel(bytes) {
	if (!bytes) return ""
	if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * A quote's brochure in the quote form: one file, uploaded like a chat file ahead of Send, and
 * posted on the Quote card by send_quote. A brief already quoted starts with its brochure, which
 * stays unless the partner removes it. `thread` returns the thread to upload into.
 */
export function useQuoteBrochure({ call, toast, thread }) {
	// { file_url, file_name, file_size, uploading, isNew }: isNew marks an upload no card owns yet.
	const brochure = ref(null)
	// Each pick or removal moves this on, so an upload that finishes after it is thrown away.
	let pickCount = 0

	function discardUpload(fileUrl) {
		call("connect.api.attachments.remove_chat_attachment", { file_url: fileUrl }).catch(() => {})
	}

	function dropUnsent() {
		const current = brochure.value
		if (current?.isNew && current.file_url) discardUpload(current.file_url)
		pickCount++
		brochure.value = null
	}

	function startBrochure(brief) {
		dropUnsent()
		if (!brief?.brochure) return
		brochure.value = {
			file_url: brief.brochure,
			file_name: brief.brochure_name,
			file_size: brief.brochure_size,
			uploading: false,
			isNew: false,
		}
	}

	async function uploadBrochure(file) {
		dropUnsent()
		const pick = pickCount
		brochure.value = { file_name: file.name, file_size: file.size, uploading: true, isNew: true }
		try {
			const saved = await useFileUpload().upload(file, {
				upload_endpoint: "/api/method/connect.api.attachments.upload_chat_attachment",
				params: { thread: thread() },
			})
			if (pick !== pickCount) return discardUpload(saved.file_url)
			brochure.value = { ...saved, uploading: false, isNew: true }
		} catch (error) {
			if (pick === pickCount) brochure.value = null
			toast.error(error?.messages?.[0] || "Couldn't upload the brochure. Try again.")
		}
	}

	// A throwaway <input>: Studio has no file-picker block.
	function pickBrochure() {
		const input = document.createElement("input")
		Object.assign(input, { type: "file", accept: BROCHURE_TYPES })
		input.addEventListener("change", () => input.files?.[0] && uploadBrochure(input.files[0]))
		input.click()
	}

	// Once the quote is sent, its card owns the upload.
	function brochureSent() {
		pickCount++
		brochure.value = null
	}

	return {
		hasQuoteBrochure: computed(() => Boolean(brochure.value)),
		isQuoteBrochureUploading: computed(() => Boolean(brochure.value?.uploading)),
		quoteBrochureLabel: computed(() => {
			const current = brochure.value
			if (!current) return ""
			if (current.uploading) return `Uploading ${current.file_name}…`
			return [current.file_name, sizeLabel(current.file_size)].filter(Boolean).join(" · ")
		}),
		quoteBrochureUrl: computed(() => (brochure.value?.uploading ? "" : brochure.value?.file_url || "")),
		pickQuoteBrochure: pickBrochure,
		removeQuoteBrochure: dropUnsent,
		startBrochure,
		brochureSent,
	}
}
