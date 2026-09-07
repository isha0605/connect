import { ref, computed } from "vue"
import { toast, call, useFileUpload } from "frappe-ui"

export default function setup(context) {
	// ---- State ----
	const selectedThread = ref("")
	const draftMessage = ref("")
	const draftAttachment = ref(null)
	const sendingMessage = ref(false)
	const togglingShortlist = ref(false)

	// ---- Threads (inbox list) ----
	function threadList() {
		return context.myThreads.data || []
	}

	function currentThread() {
		return threadList().find((t) => t.name === selectedThread.value) || {}
	}

	function amPartner() {
		return !!(context.myContext.data && context.myContext.data.partner)
	}

	// Threads carry the other side's company name directly (Partner/Customer both
	// autoname by their display name), so no extra lookup is needed here.
	function otherPartyName(thread) {
		return amPartner() ? thread.customer : thread.partner
	}

	function threadTitle() {
		const t = currentThread()
		return t.name ? otherPartyName(t) : "Select a conversation"
	}

	// WhatsApp-style: clock time for today, "Yesterday" for the day before, otherwise a
	// short date — recomputed each call rather than cached so it doesn't go stale.
	function threadListTime(thread) {
		if (!thread || !thread.last_message_at) return ""
		const d = new Date(thread.last_message_at)
		const now = new Date()
		if (d.toDateString() === now.toDateString()) {
			return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })
		}
		const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000)
		if (d.toDateString() === yesterday.toDateString()) return "Yesterday"
		return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
	}

	function threadListPreview(thread) {
		if (!thread || !thread.last_message_preview) return "No messages yet"
		const me = context.myContext.data && context.myContext.data.user
		const sender = thread.last_message_sender
		let label = sender === me ? "You" : (sender || "").split("@")[0]
		if (label && label !== "You") label = label.charAt(0).toUpperCase() + label.slice(1)
		return (label ? label + ": " : "") + thread.last_message_preview
	}

	function selectThread(item) {
		selectedThread.value = item.name
	}

	// ---- Conversation header stats ----
	function activeMemberCount() {
		return (context.threadMembers.data || []).filter((m) => !m.is_removed).length
	}

	function currentPartner() {
		return (context.partnerInfo.data || [])[0] || null
	}

	function partnerLogo() {
		const p = currentPartner()
		return p ? p.logo : ""
	}

	function responseTimeLabel() {
		const p = currentPartner()
		if (!p || !p.response_time_hours) return ""
		return "Typically " + p.response_time_hours + "h"
	}

	// No per-partner timezone field exists on the backend yet, so this shows the viewer's
	// own local time as a stand-in rather than a real "their local time" reading.
	function localTimeLabel() {
		return new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) + " local time"
	}

	const myShortlistNames = computed(() => context.myShortlist.data || [])

	function isShortlisted() {
		return myShortlistNames.value.includes(currentThread().partner)
	}

	async function toggleShortlist() {
		const partner = currentThread().partner
		if (!partner || togglingShortlist.value) return
		togglingShortlist.value = true
		try {
			if (isShortlisted()) {
				await call("connect.api.customer.remove_from_shortlist", { partner })
			} else {
				await call("connect.api.customer.add_to_shortlist", { partner })
			}
			context.myShortlist.reload()
		} catch (e) {
			toast({ title: "Could not update shortlist", text: e.messages ? e.messages[0] : e.message, icon: "x-circle", iconClasses: "text-red-600" })
		} finally {
			togglingShortlist.value = false
		}
	}

	function closeConversation() {
		if (!window.confirm("Close this conversation?")) return
		call("connect.api.threads.close_thread", { thread: selectedThread.value })
			.then(() => {
				context.myThreads.reload()
				toast({ title: "Conversation closed", icon: "check", iconClasses: "text-green-600" })
			})
			.catch((e) => {
				toast({ title: "Could not close conversation", text: e.messages ? e.messages[0] : e.message, icon: "x-circle", iconClasses: "text-red-600" })
			})
	}

	// ---- Messages ----
	function currentMessages() {
		return [...(context.messages.data || [])].sort((a, b) => new Date(a.creation).getTime() - new Date(b.creation).getTime())
	}

	function isMine(sender) {
		return sender === (context.myContext.data && context.myContext.data.user)
	}

	function formatMessageTime(item) {
		return new Date(item.creation).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase()
	}

	// ---- Composer ----
	function openFilePicker() {
		if (!selectedThread.value) return
		const input = document.createElement("input")
		input.type = "file"
		input.accept = ".pdf,.docx,.pptx,image/*"
		input.style.display = "none"
		input.addEventListener("change", () => {
			const file = input.files && input.files[0]
			if (file) uploadAttachment(file)
			input.remove()
		})
		document.body.appendChild(input)
		input.click()
	}

	function uploadAttachment(file) {
		draftAttachment.value = { file_name: file.name, uploading: true, file_url: null, file_type: null, file_size: null }
		const { upload } = useFileUpload()
		upload(file, {
			upload_endpoint: "/api/method/connect.api.attachments.upload_chat_attachment",
			params: { thread: selectedThread.value },
		})
			.then((data) => {
				if (!draftAttachment.value) return
				draftAttachment.value = { ...data, uploading: false }
			})
			.catch((e) => {
				draftAttachment.value = null
				toast({ title: "Could not upload file", text: e.messages ? e.messages[0] : e.message, icon: "x-circle", iconClasses: "text-red-600" })
			})
	}

	function removeDraftAttachment() {
		draftAttachment.value = null
	}

	async function sendMessage() {
		if (!selectedThread.value || sendingMessage.value) return
		if (draftAttachment.value && draftAttachment.value.uploading) return
		const content = draftMessage.value.trim()
		const attachment = draftAttachment.value
		if (!content && !attachment) return

		const thread = selectedThread.value
		draftMessage.value = ""
		draftAttachment.value = null
		sendingMessage.value = true
		try {
			if (content) {
				await call("connect.api.messages.send_message", { thread, content })
			}
			if (attachment) {
				await call("connect.api.messages.send_message", {
					thread,
					content: "",
					file_url: attachment.file_url,
					file_name: attachment.file_name,
					file_type: attachment.file_type,
					file_size: attachment.file_size,
				})
			}
			context.messages.reload()
			context.myThreads.reload()
		} catch (e) {
			context.messages.reload()
			toast({ title: "Could not send message", text: e.messages ? e.messages[0] : e.message, icon: "x-circle", iconClasses: "text-red-600" })
		} finally {
			sendingMessage.value = false
		}
	}

	function sendMessageOnEnter(event) {
		if (event.key === "Enter" && !event.shiftKey) {
			event.preventDefault()
			sendMessage()
		}
	}

	return {
		selectedThread,
		draftMessage,
		draftAttachment,
		sendingMessage,
		togglingShortlist,
		threadList,
		currentThread,
		amPartner,
		otherPartyName,
		threadTitle,
		threadListTime,
		threadListPreview,
		selectThread,
		activeMemberCount,
		currentPartner,
		partnerLogo,
		responseTimeLabel,
		localTimeLabel,
		isShortlisted,
		toggleShortlist,
		closeConversation,
		currentMessages,
		isMine,
		formatMessageTime,
		openFilePicker,
		removeDraftAttachment,
		sendMessage,
		sendMessageOnEnter,
	}
}
