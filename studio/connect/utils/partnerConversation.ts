// The customer's chat with the partner, as a lead and a customer both show it in their Messages
// tab: the thread's messages and cards, the message box (text, files, templates, a quote, a
// meeting invite), and the partner's answers on the cards (a brief: Interested opens the quote,
// Not interested declines it; a hire request: accept or decline). It is where a partner's
// team writes to a customer, so everything here posts into the customer's thread.

import { computed, onScopeDispose, ref, watch } from "vue"
import { setConfig, useFileUpload } from "frappe-ui"
import { useMessageTemplates } from "@app/utils/messageTemplates"
import {
	MEETING_DURATIONS,
	clockOrDate,
	copyText,
	emptyMeeting,
	isoDay,
	meetingTimeLabel,
	meetingValues,
	toFollowUpRows,
	toTime,
} from "@app/utils/partnerRecords"

const RUPEES = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })
const MAX_QUOTE_WEEKS = 104
const QUOTE_NOTE_LIMIT = 300
const HIRE_STATUS_LABELS = { "Hire Requested": "Waiting for your answer", Hired: "Accepted" }

const escapeHtml = (text) => String(text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
const paragraphs = (text) => escapeHtml(text).split("\n").map((line) => `<p>${line}</p>`).join("")
const FILE_TYPES = ".pdf,.docx,.pptx,image/*"

const WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
const minutesOfDay = (hhmm) => {
	const [hours, minutes] = (hhmm || "00:00").split(":")
	return Number(hours) * 60 + Number(minutes || 0)
}

// Outside the sender's own working hours (Settings → Working hours), by this browser's clock.
function isOutsideWorkHours(settings) {
	const now = new Date()
	if (!(settings.work_days || []).includes(WEEKDAYS[now.getDay()])) return true
	const minutes = now.getHours() * 60 + now.getMinutes()
	return minutes < minutesOfDay(settings.work_start) || minutes >= minutesOfDay(settings.work_end)
}

// Every event the server sends a thread's members when its messages change.
const THREAD_EVENTS = ["connect_new_message", "connect_message_edited", "connect_message_deleted"]

// A file's icon and its colours, by kind. Full "lucide-" names: the Studio build only ships
// the icons it finds written out.
const FILE_LOOKS = [
	{ test: (type) => type.startsWith("image/"), icon: "lucide-image", bg: "var(--surface-green-2)", color: "var(--ink-green-6)" },
	{ test: (type) => type.includes("wordprocessingml"), icon: "lucide-file-text", bg: "var(--surface-blue-2)", color: "var(--ink-blue-6)" },
	{ test: (type) => type.includes("presentationml"), icon: "lucide-monitor", bg: "var(--surface-amber-2)", color: "var(--ink-amber-7)" },
	{ test: (type) => type === "application/pdf", icon: "lucide-file", bg: "var(--surface-red-2)", color: "var(--ink-red-6)" },
]
const PLAIN_FILE_LOOK = { icon: "lucide-file", bg: "var(--surface-gray-2)", color: "var(--ink-gray-6)" }
const fileLook = (type) => FILE_LOOKS.find((look) => look.test(type || "")) || PLAIN_FILE_LOOK
const attachmentIcon = (type) => fileLook(type).icon

function fileSizeLabel(bytes) {
	if (!bytes && bytes !== 0) return ""
	if (bytes < 1024) return `${bytes} B`
	if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// What a file's card and its preview read. The name goes into an <img alt="…"> written as
// HTML, and it is whatever the uploader called the file, so it is escaped here.
function fileCard(message) {
	const look = fileLook(message.file_type)
	return {
		isImage: (message.file_type || "").startsWith("image/"),
		icon: look.icon,
		iconBg: look.bg,
		iconColor: look.color,
		sizeLabel: fileSizeLabel(message.file_size),
		safeName: escapeHtml(message.file_name).replace(/"/g, "&quot;"),
	}
}

function hireStatusLabel(message) {
	if (message.status === "Hire Declined") return `Declined: ${message.decline_reason || ""}`
	return HIRE_STATUS_LABELS[message.status] || "Withdrawn"
}

function quoteError(amount, weeks, note) {
	if (!(Number(amount) > 0)) return "Enter an amount above 0."
	if (!Number.isInteger(Number(weeks)) || weeks < 1 || weeks > MAX_QUOTE_WEEKS) return `Enter whole weeks, 1 to ${MAX_QUOTE_WEEKS}.`
	if (note.length > QUOTE_NOTE_LIMIT) return `Keep the note to ${QUOTE_NOTE_LIMIT} characters.`
	return ""
}

// `record` is the server's lead or customer (name, thread, messages, follow_ups,
// is_customer_revealed), `reload` reads it again after anything here changes the thread, and
// `followUpMethod` is the page's log_*_follow_up, which also sends a meeting invite. `me` is
// the signed-in user (a ref), and `socket` is Studio's realtime connection.
export function useConversation({ call, toast, record, reload, followUpMethod, me, socket }) {
	const thread = computed(() => record.value?.thread || "")

	const messages = computed(() => {
		const current = record.value
		if (!current) return []
		const followUps = toFollowUpRows(current.follow_ups || [])
		return (current.messages || []).map((m) => ({
			...m,
			time: clockOrDate(toTime(m.at)),
			isYou: m.from === "you",
			// P for the partner's side, C for the customer's: who wrote is plain at a glance.
			avatarLabel: m.from === "you" ? "P" : "C",
			isWaiting: m.kind === "bid" && !current.is_customer_revealed,
			...(m.kind === "meeting" ? meetingCard(m, followUps) : {}),
			...(m.kind === "file" ? fileCard(m) : {}),
			body: messageBody(m),
			price: m.amount ? RUPEES.format(m.amount) : "",
			weeksLabel: m.weeks ? `about ${m.weeks} weeks` : "",
			hireStatus: m.kind === "hire" ? hireStatusLabel(m) : "",
			menu: m.kind === "text" ? messageMenu(m) : [],
		}))
	})

	function meetingCard(message, followUps) {
		const invite = followUps.find((row) => row.id === message.follow_up)
		return {
			meetingTime: meetingTimeLabel(toTime(message.starts_at), message.duration_minutes),
			canJoin: invite ? invite.canJoin : Boolean(message.link),
		}
	}

	function messageBody(message) {
		return message.kind === "text" ? paragraphs(message.text) : ""
	}

	// ── Live updates: a message from anyone else shows without a refresh ──────
	// The server tells a thread's members when its messages change (notify_thread_members).
	function onThreadEvent(payload) {
		if (payload?.thread && payload.thread === thread.value) reload()
	}
	THREAD_EVENTS.forEach((event) => socket.on(event, onThreadEvent))
	onScopeDispose(() => THREAD_EVENTS.forEach((event) => socket.off(event, onThreadEvent)))

	// ── A file: opened over the whole page, and downloaded from there or from its card ──
	const showFilePreviewDialog = ref(false)
	const previewFile = ref(null)

	function openFilePreview(file) {
		previewFile.value = file
		showFilePreviewDialog.value = true
	}

	// The preview is a plain overlay, not a Dialog, so Escape is ours to handle.
	function closePreviewOnEscape(event) {
		if (event.key === "Escape") showFilePreviewDialog.value = false
	}
	window.addEventListener("keydown", closePreviewOnEscape)
	onScopeDispose(() => window.removeEventListener("keydown", closePreviewOnEscape))

	// Fetched, then saved from a blob: a plain link would open an image or a PDF in the tab.
	async function downloadFile(file, event = null) {
		event?.stopPropagation()
		if (!file?.attachment) return
		try {
			const response = await fetch(file.attachment)
			if (!response.ok) throw new Error("Download failed")
			const link = document.createElement("a")
			link.href = URL.createObjectURL(await response.blob())
			link.download = file.file_name || ""
			link.click()
			URL.revokeObjectURL(link.href)
		} catch {
			toast.error("Couldn't download the file.")
		}
	}

	// Without the limit, an oversized file fails as a network error, not as a message that says why.
	call("frappe.core.api.file.get_max_file_size")
		.then((limit) => limit && setConfig("maxFileSize", limit))
		.catch(() => {})

	function messageMenu(message) {
		const link = `${window.location.href.split("#")[0]}#msg-${message.id}`
		return [
			{ label: "Copy text", icon: "lucide-copy", onClick: () => copyText(message.text || "", toast, "Copied") },
			{ label: "Copy link", icon: "lucide-link", onClick: () => copyText(link, toast, "Link copied") },
		]
	}

	// ── The message box: text, files, a template, a quote, a meeting invite ──
	const messageDraft = ref("")
	const sending = ref(false)
	const draftAttachments = ref([])
	const isUploading = computed(() => draftAttachments.value.some((file) => file.uploading))
	let nextAttachmentId = 1

	function resetDraft() {
		messageDraft.value = ""
		draftAttachments.value = []
		quoteOpen.value = false
	}

	// A throwaway <input>: Studio has no file-picker block. Each file uploads on its own, ahead
	// of Send, and becomes a message only when the box is sent.
	function pickFiles() {
		const input = document.createElement("input")
		Object.assign(input, { type: "file", multiple: true, accept: FILE_TYPES })
		input.addEventListener("change", () => Array.from(input.files || []).forEach(uploadFile))
		input.click()
	}

	async function uploadFile(file) {
		const id = nextAttachmentId++
		draftAttachments.value.push({ id, file_name: file.name, icon: attachmentIcon(file.type), uploading: true })
		try {
			const saved = await useFileUpload().upload(file, {
				upload_endpoint: "/api/method/connect.api.attachments.upload_chat_attachment",
				params: { thread: thread.value },
			})
			const current = draftAttachments.value.find((row) => row.id === id)
			// Removed while it was uploading: the file has no message to belong to.
			if (!current) return discardUpload(saved.file_url)
			Object.assign(current, saved, { uploading: false })
		} catch (error) {
			draftAttachments.value = draftAttachments.value.filter((row) => row.id !== id)
			toast.error(error?.messages?.[0] || "Couldn't upload the file.")
		}
	}

	const discardUpload = (file_url) => call("connect.api.attachments.remove_chat_attachment", { file_url }).catch(() => {})

	function removeAttachment(file) {
		draftAttachments.value = draftAttachments.value.filter((row) => row.id !== file.id)
		if (file.file_url) discardUpload(file.file_url)
	}

	const canSend = computed(() => {
		if (sending.value || isUploading.value) return false
		if (quoteOpen.value) return Number(quoteAmount.value) > 0 && Number(quoteWeeks.value) > 0
		return Boolean(messageDraft.value.trim() || draftAttachments.value.length)
	})

	// A silent message is delivered and shows live, but sends the customer no notification.
	// Ctrl/Cmd+Shift+Enter asks for one; "Always send silently" makes every message silent
	// outside the sender's working hours, as on the Messages page.
	const workSettings = ref(null)
	call("connect.api.account.get_my_work_settings")
		.then((settings) => (workSettings.value = settings))
		.catch(() => {})

	function isSilentByDefault() {
		const settings = workSettings.value
		return settings?.after_hours_behavior === "Always send silently" && isOutsideWorkHours(settings)
	}

	async function send(silent = false) {
		if (!canSend.value) return
		sending.value = true
		try {
			await (quoteOpen.value ? sendQuote() : sendMessage(silent || isSilentByDefault() ? 1 : 0))
			await reload()
		} catch (error) {
			toast.error(error?.messages?.[0] || "Couldn't send. Try again.")
		} finally {
			sending.value = false
		}
	}

	async function sendMessage(silent) {
		const content = messageDraft.value.trim()
		const files = draftAttachments.value.filter((file) => file.file_url)
		resetDraft()
		if (content) await call("connect.api.messages.send_message", { thread: thread.value, content, silent })
		for (const { file_url, file_name, file_type, file_size } of files) {
			const file = { file_url, file_name, file_type, file_size }
			await call("connect.api.messages.send_message", { thread: thread.value, content: "", silent, ...file })
		}
	}

	function onComposerKey(event) {
		if (event.key !== "Enter" || event.altKey) return
		const isSilentSend = event.shiftKey && (event.ctrlKey || event.metaKey)
		// Shift+Enter alone is a new line, and Ctrl/Cmd+Enter is left to the browser.
		if (!isSilentSend && (event.shiftKey || event.ctrlKey || event.metaKey)) return
		event.preventDefault()
		send(isSilentSend)
	}

	// A template picked in the Templates dialog. One with {{ variables }} is filled in on the
	// server for this thread; plain text goes straight in.
	async function fillFromTemplate(template) {
		let content = template.content || ""
		if (/\{\{|\{%/.test(content)) {
			const args = { content, thread: thread.value }
			content = await call("connect.api.message_templates.render_message_template", args).catch(() => content)
		}
		messageDraft.value = content
	}
	const templates = useMessageTemplates({ call, toast, me, onInsert: fillFromTemplate })

	// ── A quote, written in the message box: amount, timeline, and the text as its note ──
	// The briefs in this thread the caller may still quote on (none for people outside sales).
	const quotableBriefs = ref([])
	const quoteOpen = ref(false)
	const quoteBrief = ref("")
	const quoteAmount = ref("")
	const quoteWeeks = ref("")

	function loadQuotableBriefs() {
		quotableBriefs.value = []
		if (!thread.value) return
		call("connect.api.projects.quotable_briefs", { thread: thread.value })
			.then((rows) => (quotableBriefs.value = rows || []))
			.catch(() => {})
	}
	// The record is read again after every change here, which is when a brief stops being quotable.
	watch(record, loadQuotableBriefs, { immediate: true })

	// A brief already quoted opens with its quote, so the partner changes only what is new.
	function openQuote(name = "") {
		const brief = quotableBriefs.value.find((row) => row.name === name) || quotableBriefs.value[0]
		if (!brief) return
		quoteBrief.value = brief.name
		quoteAmount.value = brief.amount ? String(brief.amount) : ""
		quoteWeeks.value = brief.weeks ? String(brief.weeks) : ""
		if (brief.note && !messageDraft.value.trim()) messageDraft.value = brief.note
		quoteOpen.value = true
	}

	async function sendQuote() {
		const note = messageDraft.value.trim()
		const error = quoteError(quoteAmount.value, Number(quoteWeeks.value), note)
		if (error) throw { messages: [error] }
		const args = { quote: quoteBrief.value, amount: Number(quoteAmount.value), weeks: Number(quoteWeeks.value), note }
		await call("connect.api.projects.send_quote", args)
		resetDraft()
		toast.success("Quote sent")
	}

	// ── A meeting invite: a card in the thread the customer accepts or declines ──
	const meetingOpen = ref(false)
	const meetingForm = ref(emptyMeeting())
	const scheduling = ref(false)

	function startMeeting() {
		meetingForm.value = emptyMeeting()
		meetingOpen.value = true
	}

	async function saveMeeting() {
		if (scheduling.value) return
		scheduling.value = true
		try {
			await call(followUpMethod, { name: record.value.name, values: meetingValues(meetingForm.value) })
			meetingOpen.value = false
			toast.success("Meeting invite sent")
			// The invite is a card in the thread too, so read the whole record again.
			await reload()
		} catch (error) {
			toast.error(error?.messages?.[0] || "Couldn't schedule the meeting.")
		} finally {
			scheduling.value = false
		}
	}

	// One answer at a time: every card's buttons wait while another is being saved.
	const answering = ref(false)
	async function answer(method, args, done, failed) {
		if (answering.value) return false
		answering.value = true
		try {
			await call(method, args)
			toast.success(done)
			await reload()
			return true
		} catch (error) {
			toast.error(error?.messages?.[0] || failed)
			return false
		} finally {
			answering.value = false
		}
	}

	// ── A brief: Interested opens the quote, Not interested is final ──────────
	const declineBriefOpen = ref(false)
	const declineBriefQuote = ref("")

	function askDeclineBrief(message) {
		declineBriefQuote.value = message.quote
		declineBriefOpen.value = true
	}

	async function declineBrief() {
		const args = { quote: declineBriefQuote.value }
		const failed = "Couldn't save your answer. Try again."
		if (await answer("connect.api.projects.decline_brief", args, "The customer has been told", failed)) {
			declineBriefOpen.value = false
		}
	}

	// ── A hire request: the partner's admin accepts, or declines with a reason ──
	const declineHireOpen = ref(false)
	const declineHireQuote = ref("")
	const declineHireReason = ref("")

	function respondToHire(quote, accept, reason = "") {
		const args = { quote, accept: accept ? 1 : 0, reason }
		const done = accept ? "Hire accepted" : "Hire declined"
		return answer("connect.api.projects.respond_to_hire", args, done, "Couldn't answer the hire request. Try again.")
	}

	function askDeclineHire(message) {
		declineHireQuote.value = message.quote
		declineHireReason.value = ""
		declineHireOpen.value = true
	}

	async function declineHire() {
		const reason = declineHireReason.value.trim()
		if (!reason) return toast.error("Say why, so the customer knows.")
		if (await respondToHire(declineHireQuote.value, false, reason)) declineHireOpen.value = false
	}

	return {
		messages,
		messageDraft,
		resetDraft,
		canSend,
		sending,
		send,
		onComposerKey,
		composerPlaceholder: computed(() => (quoteOpen.value ? "Add a note for the customer (optional)…" : "Type a message…")),
		sendLabel: computed(() => (quoteOpen.value ? "Send quote" : "Send")),
		showFilePreviewDialog,
		previewFile,
		openFilePreview,
		downloadFile,
		draftAttachments,
		pickFiles,
		removeAttachment,
		...templates,
		canQuote: computed(() => quotableBriefs.value.length > 0),
		quoteOpen,
		quoteBrief,
		quoteAmount,
		quoteWeeks,
		quoteBriefOptions: computed(() => quotableBriefs.value.map((brief) => ({ label: brief.project_name, value: brief.name }))),
		openQuote,
		startQuote: (message) => openQuote(message.quote),
		closeQuote: () => (quoteOpen.value = false),
		meetingOpen,
		meetingForm,
		meetingDurations: MEETING_DURATIONS,
		// A meeting is still to come: earlier days are greyed out.
		meetingMinDate: isoDay(new Date()),
		scheduling,
		startMeeting,
		saveMeeting,
		closeMeeting: () => (meetingOpen.value = false),
		joinMeeting: (link) => link && window.open(link, "_blank", "noopener"),
		answering,
		declineBriefOpen,
		askDeclineBrief,
		declineBrief,
		closeDeclineBrief: () => (declineBriefOpen.value = false),
		acceptHire: (message) => respondToHire(message.quote, true),
		declineHireOpen,
		declineHireReason,
		askDeclineHire,
		declineHire,
		closeDeclineHire: () => (declineHireOpen.value = false),
	}
}
