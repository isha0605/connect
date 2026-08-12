import { ref, computed, watch, onScopeDispose } from "vue"
import { toast, call, useFileUpload, initSocket } from "frappe-ui"

export default function setup(context) {
	// ---- State ----
	const selectedThread = ref("")
	const draftMessage = ref("")
	const draftAttachments = ref([])
	let nextAttachmentId = 1
	const showMembersDialog = ref(false)
	const showMediaDialog = ref(false)
	const showTemplatesDialog = ref(false)
	const showInlineTemplates = ref(false)
	const mediaTab = ref("Links")
	const showAddMemberDialog = ref(false)
	const newMemberEmail = ref("")
	const newMemberPermission = ref("Write")

	// ---- Threads ----
	function currentThread() {
		return (context.myThreads.data || []).find((t) => t.name === selectedThread.value) || {}
	}

	function otherPartyName(thread) {
		const amPartner = context.myContext.data && context.myContext.data.partner
		return amPartner ? thread.customer : thread.partner
	}

	function threadTitle() {
		const t = currentThread()
		if (!t.name) return "Select a conversation"
		return otherPartyName(t)
	}

	// WhatsApp-style: clock time for today, "Yesterday" for the day before, otherwise a
	// short date — recomputed against `now` each call rather than cached, so it doesn't
	// silently go stale for a session left open across midnight.
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
		return (thread && thread.last_message) || "No messages yet"
	}

	function threadCreatedLabel() {
		const t = currentThread()
		if (!t.creation) return ""
		return "Group created on " + formatOrdinalDate(new Date(t.creation))
	}

	function isPanelOpen() {
		return showMembersDialog.value || showMediaDialog.value || showTemplatesDialog.value
	}

	function myMessageTemplates() {
		return context.myTemplates.data || []
	}

	function selectThread(name) {
		selectedThread.value = name
		context.messages.filters = { thread: name }
		context.messages.reload()
		context.threadMembers.filters = { thread: name }
		context.threadMembers.reload()
		context.threadAdmins.params = { thread: name }
		context.threadAdmins.reload()
		call("connect.api.mark_thread_read", { thread: name })
			.then(() => context.myThreads.reload())
			.catch(() => {})
	}

	// default to the first (most recently active) thread once the list loads
	watch(
		() => context.myThreads?.data,
		(threads) => {
			if (selectedThread.value || !threads || !threads.length) return
			selectThread(threads[0].name)
		},
		{ immediate: true },
	)

	// ---- Realtime ----
	// A dedicated connection for this page rather than reusing Studio's own — page scripts
	// run in a detached effect scope with no component instance, so the socket Studio
	// provides via Vue's provide()/inject() further up the tree isn't reachable here.
	// connect.connect.notifications.notify_thread_members publishes this event straight to
	// a thread's other members the instant a message is sent — the sender's own tab already
	// reloads after sendMessage(), so this is purely for tabs that didn't send it.
	// frappe-ui's initSocket() only computes the connection namespace from window.location in
	// dev builds — in production it reads window.site_name, which nothing on this page sets,
	// so it silently connects to namespace "/undefined" and the server rejects it (400 on the
	// socket.io handshake). window.location.hostname is what the server actually expects
	// (matches its own site-name resolution from the request's Origin header) in both cases.
	if (!(window as any).site_name) (window as any).site_name = window.location.hostname
	const socket = initSocket()
	socket.on("connect", () => console.log("[connect realtime] connected, socket id:", socket.id))
	socket.on("connect_error", (err) => console.error("[connect realtime] connect_error:", err.message))
	socket.on("disconnect", (reason) => console.warn("[connect realtime] disconnected:", reason))
	function handleNewMessage(payload) {
		console.log("[connect realtime] connect_new_message received:", payload, "selectedThread:", selectedThread.value)
		if (payload.thread === selectedThread.value) context.messages.reload()
		context.myThreads.reload()
	}
	socket.on("connect_new_message", handleNewMessage)
	onScopeDispose(() => socket.off("connect_new_message", handleNewMessage))

	function closeThread() {
		if (!window.confirm("Close this thread?")) return
		call("connect.api.close_thread", { thread: selectedThread.value })
			.then(() => {
				context.myThreads.reload()
				context.messages.reload()
				toast({ title: "Thread closed", icon: "check", iconClasses: "text-green-600" })
			})
			.catch((e) => {
				toast({
					title: "Could not close thread",
					text: e.messages ? e.messages[0] : e.message,
					icon: "x-circle",
					iconClasses: "text-red-600",
				})
			})
	}

	// ---- Admin checks ----
	function isPartnerAdmin() {
		return !!(context.myContext.data && context.myContext.data.partner && context.myContext.data.partner.is_admin)
	}

	function isCustomerAdmin() {
		return !!(context.myContext.data && context.myContext.data.customer && context.myContext.data.customer.is_admin)
	}

	function isAnyAdmin() {
		return isPartnerAdmin() || isCustomerAdmin()
	}

	function isRowAdmin(item) {
		return item.side === "Partner" ? isPartnerAdmin() : isCustomerAdmin()
	}

	// ---- Members ----
	function activeMembers() {
		return (context.threadMembers.data || []).filter((m) => !m.is_removed)
	}

	// a trailing "@partial-name" at the very end of the draft triggers the picker — mentions
	// mid-message aren't supported since Studio's TextInput doesn't expose cursor position.
	// Derived straight from draftMessage on every call (not a watch()) so it can't fall out of
	// sync with whatever's actually rendered in the input.
	function mentionMatch() {
		return /(^|\s)@([^\s@]*)$/.exec(draftMessage.value || "")
	}

	function isMentioning() {
		return !!mentionMatch()
	}

	function filteredMentionMembers() {
		const match = mentionMatch()
		const query = (match ? match[2] : "").toLowerCase()
		return activeMembers()
			.map((m) => ({ member: m, name: (m.user || "").split("@")[0].toLowerCase() }))
			.filter((x) => x.name.includes(query))
			.sort((a, b) => {
				const aStarts = a.name.startsWith(query) ? 0 : 1
				const bStarts = b.name.startsWith(query) ? 0 : 1
				return aStarts !== bStarts ? aStarts - bStarts : a.name.localeCompare(b.name)
			})
			.map((x) => x.member)
	}

	function insertMention(member) {
		const name = (member.user || "").split("@")[0]
		draftMessage.value = draftMessage.value.replace(/(^|\s)@([^\s@]*)$/, (_match, prefix) => prefix + "@" + name + " ")
	}

	function insertTemplate(template) {
		draftMessage.value = template.content
		showInlineTemplates.value = false
	}

	// message-content renders this via the raw-HTML component (not a plain TextBlock) so
	// @mentions can render bold — the content is user-typed free text, so it's escaped first
	// (neutralizing any real markup) and only then are our own <strong> tags added back in
	// around @word tokens, which is what keeps this safe from XSS.
	function formatMessageContent(item) {
		const raw = (item && item.content) || ""
		const div = document.createElement("div")
		div.textContent = raw
		const escaped = div.innerHTML
		const withMentions = escaped.replace(/@([^\s@]+)/g, '<span style="font-weight: 600">@$1</span>')
		const time = item ? formatMessageTime(item) : ""
		const timeSpan =
			'<span style="float: right; margin-left: 8px; margin-top: 6px; margin-right: -6px; font-size: 9px; ' +
			'line-height: 12px; color: var(--ink-gray-5); white-space: nowrap;">' +
			time +
			"</span>"
		return withMentions + timeSpan
	}

	function addMember() {
		if (!newMemberEmail.value) {
			toast({ title: "Enter an email", icon: "x-circle", iconClasses: "text-red-600" })
			return
		}
		const side =
			context.myContext.data && context.myContext.data.customer
				? "Customer"
				: context.myContext.data && context.myContext.data.partner
					? "Partner"
					: null
		if (!side) {
			toast({ title: "Only admins can add members", icon: "x-circle", iconClasses: "text-red-600" })
			return
		}
		call("connect.api.add_thread_member", {
			thread: selectedThread.value,
			email: newMemberEmail.value,
			side: side,
			permission: newMemberPermission.value,
		})
			.then((data) => {
				showAddMemberDialog.value = false
				newMemberEmail.value = ""
				newMemberPermission.value = "Write"
				context.threadMembers.reload()
				toast({
					title: data && data.created_user ? "New account created and added" : "Member added",
					icon: "check",
					iconClasses: "text-green-600",
				})
			})
			.catch((e) => {
				toast({
					title: "Could not add member",
					text: e.messages ? e.messages[0] : e.message,
					icon: "x-circle",
					iconClasses: "text-red-600",
				})
			})
	}

	function makeAdmin(item) {
		if (!window.confirm(`Make ${item.user} the admin? You will lose admin rights.`)) return
		call("connect.api.make_thread_admin", { thread: selectedThread.value, member: item.name })
			.then(() => {
				context.myContext.reload()
				context.threadAdmins.reload()
				toast({ title: "Admin transferred", icon: "check", iconClasses: "text-green-600" })
			})
			.catch((e) => {
				toast({
					title: "Could not transfer admin",
					text: e.messages ? e.messages[0] : e.message,
					icon: "x-circle",
					iconClasses: "text-red-600",
				})
			})
	}

	function removeMember(item) {
		if (!window.confirm(`Remove ${item.user} from this thread?`)) return
		call("connect.api.remove_thread_member", { thread: selectedThread.value, member: item.name })
			.then(() => {
				context.threadMembers.reload()
				toast({ title: "Member removed", icon: "check", iconClasses: "text-green-600" })
			})
			.catch((e) => {
				toast({
					title: "Could not remove member",
					text: e.messages ? e.messages[0] : e.message,
					icon: "x-circle",
					iconClasses: "text-red-600",
				})
			})
	}

	function memberRowOptions(item) {
		const disabled = !isRowAdmin(item)
		return [
			{ label: "Make admin", icon: "lucide-crown", disabled, onClick: () => makeAdmin(item) },
			{ label: "Remove from channel", icon: "lucide-user-minus", theme: "red", disabled, onClick: () => removeMember(item) },
		]
	}

	// ---- Messages ----
	const uploadingFile = computed(() => draftAttachments.value.some((a) => a.uploading))

	async function sendMessage() {
		if (!selectedThread.value || uploadingFile.value) return
		const readyAttachments = draftAttachments.value.filter((a) => a.file_url)
		const content = draftMessage.value.trim()
		if (!content && !readyAttachments.length) return

		const thread = selectedThread.value
		draftMessage.value = ""
		draftAttachments.value = []

		try {
			if (content) {
				await call("connect.api.send_message", { thread, content })
			}
			for (const a of readyAttachments) {
				await call("connect.api.send_message", {
					thread,
					content: "",
					file_url: a.file_url,
					file_name: a.file_name,
					file_type: a.file_type,
					file_size: a.file_size,
				})
			}
			context.messages.reload()
		} catch (e) {
			toast({
				title: "Could not send message",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		}
	}

	// picking files happens through a throwaway <input>, created on demand — Studio's
	// component set has no file-picker element, and a hidden one built by hand is the
	// smallest way to reach the browser's native file dialog. Multiple files can be picked
	// (or the button clicked again while others are still uploading) — each is tracked and
	// uploaded independently, same as the reference chat UI.
	function openFilePicker() {
		if (!selectedThread.value) return
		const input = document.createElement("input")
		input.type = "file"
		input.multiple = true
		input.accept = ".pdf,.docx,.pptx,image/*"
		input.style.display = "none"
		input.addEventListener("change", () => {
			Array.from(input.files || []).forEach(uploadFile)
			input.remove()
		})
		document.body.appendChild(input)
		input.click()
	}

	// uploaded ahead of Send so the composer can show a live progress state and a remove
	// button per file — a file only becomes part of a real message once sendMessage is called.
	// Tracked by `id` rather than object reference: draftAttachments is a Vue ref array, so
	// items read back out of it are reactive proxies, never `===` to the raw object pushed in.
	function uploadFile(file) {
		const id = nextAttachmentId++
		draftAttachments.value.push({
			id,
			file_name: file.name,
			uploading: true,
			file_url: null,
			file_type: null,
			file_size: null,
		})

		const { upload } = useFileUpload()
		upload(file, {
			upload_endpoint: "/api/method/connect.api.upload_chat_attachment",
			params: { thread: selectedThread.value },
		})
			.then((data) => {
				const current = draftAttachments.value.find((a) => a.id === id)
				if (!current) {
					// removed while it was still uploading — clean up the now-orphaned file
					call("connect.api.remove_chat_attachment", { file_url: data.file_url }).catch(() => {})
					return
				}
				current.file_url = data.file_url
				current.file_name = data.file_name
				current.file_type = data.file_type
				current.file_size = data.file_size
				current.uploading = false
			})
			.catch((e) => {
				draftAttachments.value = draftAttachments.value.filter((a) => a.id !== id)
				toast({
					title: "Could not upload file",
					text: e.messages ? e.messages[0] : e.message,
					icon: "x-circle",
					iconClasses: "text-red-600",
				})
			})
	}

	function removeAttachment(item) {
		draftAttachments.value = draftAttachments.value.filter((a) => a.id !== item.id)
		if (item.file_url) {
			call("connect.api.remove_chat_attachment", { file_url: item.file_url }).catch((e) => {
				toast({
					title: "Could not remove attachment",
					text: e.messages ? e.messages[0] : e.message,
					icon: "x-circle",
					iconClasses: "text-red-600",
				})
			})
		}
	}

	function formatFileSize(bytes) {
		if (!bytes && bytes !== 0) return ""
		if (bytes < 1024) return bytes + " B"
		if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB"
		return (bytes / (1024 * 1024)).toFixed(1) + " MB"
	}

	function attachmentIcon(item) {
		const type = (item && item.file_type) || ""
		if (type.includes("wordprocessingml") || type === "application/msword") return "file-text"
		if (type.includes("presentationml") || type === "application/vnd.ms-powerpoint") return "monitor"
		if (type === "application/pdf") return "file"
		if (type.startsWith("image/")) return "image"
		return "file"
	}

	function attachmentIconBg(item) {
		const type = (item && item.file_type) || ""
		if (type.includes("wordprocessingml") || type === "application/msword") return "var(--surface-blue-2)"
		if (type.includes("presentationml") || type === "application/vnd.ms-powerpoint") return "var(--surface-amber-2)"
		if (type === "application/pdf") return "var(--surface-red-2)"
		if (type.startsWith("image/")) return "var(--surface-green-2)"
		return "var(--surface-gray-2)"
	}

	function attachmentIconColor(item) {
		const type = (item && item.file_type) || ""
		if (type.includes("wordprocessingml") || type === "application/msword") return "var(--ink-blue-6)"
		if (type.includes("presentationml") || type === "application/vnd.ms-powerpoint") return "var(--ink-amber-7)"
		if (type === "application/pdf") return "var(--ink-red-6)"
		if (type.startsWith("image/")) return "var(--ink-green-6)"
		return "var(--ink-gray-6)"
	}

	function isImageFile(item) {
		return !!(item && item.file_type && item.file_type.startsWith("image/"))
	}

	// window.open(url, "_blank") flashes a new tab open-then-closed for URLs that trigger a
	// direct download (nothing to display) — an <a download> click saves the file in place,
	// with no tab, no navigation, no flash.
	function downloadFile(item, event) {
		if (event) {
			event.preventDefault()
			event.stopPropagation()
		}
		if (!item || !item.attachment) return
		const link = document.createElement("a")
		link.href = item.attachment
		link.download = item.file_name || ""
		document.body.appendChild(link)
		link.click()
		link.remove()
	}

	// ---- File preview dialog ----
	const showFilePreviewDialog = ref(false)
	const previewFile = ref(null)

	function openFilePreview(item) {
		previewFile.value = item
		showFilePreviewDialog.value = true
	}

	function sendMessageOnEnter(event) {
		if (event && event.key === "Enter") {
			event.preventDefault()
			if (isMentioning()) {
				const matches = filteredMentionMembers()
				if (matches.length) {
					insertMention(matches[0])
					return
				}
			}
			sendMessage()
		}
	}

	function isMine(sender) {
		return sender === (context.myContext.data && context.myContext.data.user)
	}

	// messages are grouped into per-day sections (see groupedMessages) so `index` here is local
	// to the current day's group, not the flat position in context.messages.data — the first
	// message of a day is never grouped, everything after that is looked up by its global
	// neighbour (safe, since a non-zero local index guarantees the previous message is the same day).
	function isGrouped(item, index) {
		if (index <= 0) return false
		const idx = (context.messages.data || []).findIndex((m) => m.name === item.name)
		if (idx <= 0) return false
		const prev = context.messages.data[idx - 1]
		if (!prev || prev.sender !== item.sender || prev.message_type === "System") return false
		const gapMs = new Date(item.creation).getTime() - new Date(prev.creation).getTime()
		return gapMs <= 2 * 60 * 1000
	}

	// consecutive files from the same sender, sent within 2 minutes of each other, are merged
	// into one synthetic "cluster" item so they render as a single wrapped row with one time
	// underneath instead of a separate full-width row (with its own time) per file
	function clusterFileMessages(items) {
		const result = []
		for (const item of items) {
			const prev = result[result.length - 1]
			const isFile = item.message_type === "File"
			if (
				isFile &&
				prev &&
				prev.isFileCluster &&
				prev.sender === item.sender &&
				new Date(item.creation).getTime() - new Date(prev.creation).getTime() <= 2 * 60 * 1000
			) {
				prev.files.push(item)
				prev.creation = item.creation
			} else if (isFile) {
				result.push({
					isFileCluster: true,
					name: "cluster-" + item.name,
					sender: item.sender,
					creation: item.creation,
					message_type: "FileCluster",
					files: [item],
				})
			} else {
				result.push(item)
			}
		}
		return result
	}

	// buckets the flat, chronologically-sorted message list into per-day sections, each with a
	// sticky date header rendered once per section instead of a divider re-checked per message
	const groupedMessages = computed(() => {
		const groups = []
		let lastKey = null
		for (const item of context.messages.data || []) {
			const key = new Date(item.creation).toDateString()
			if (key !== lastKey) {
				groups.push({ dateKey: key, dateLabel: formatDateDivider(item), items: [] })
				lastKey = key
			}
			groups[groups.length - 1].items.push(item)
		}
		groups.forEach((g) => {
			g.items = clusterFileMessages(g.items)
		})
		return groups
	})

	function formatMessageTime(item) {
		return new Date(item.creation).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase()
	}

	function formatOrdinalDate(date) {
		const day = date.getDate()
		const suffix =
			day % 10 === 1 && day !== 11 ? "st" : day % 10 === 2 && day !== 12 ? "nd" : day % 10 === 3 && day !== 13 ? "rd" : "th"
		return day + suffix + " " + date.toLocaleDateString("en-US", { month: "long", year: "numeric" })
	}

	function formatDateDivider(item) {
		return formatOrdinalDate(new Date(item.creation))
	}

	function formatFullDateTime(item) {
		const d = new Date(item.creation)
		const timeStr = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase()
		return formatOrdinalDate(d) + ", " + timeStr
	}

	// ---- Avatars ----
	// frappe-ui's Avatar component only takes a `theme` name (not a raw color), so a key
	// just hashes to one of its 5 non-gray themes — same person, same color, every time.
	const AVATAR_THEMES = ["blue", "green", "amber", "red", "violet"]

	function avatarHash(key) {
		const s = String(key || "")
		let h = 0
		for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % AVATAR_THEMES.length
		return h
	}

	function avatarTheme(key) {
		return AVATAR_THEMES[avatarHash(key)]
	}

	// ---- Media ----
	const mediaSearchQuery = ref("")
	const mediaViewMode = ref("list")

	// a leftover query from the Files tab would otherwise silently filter out every
	// link (and vice versa) since both tabs share one search box
	watch(mediaTab, () => {
		mediaSearchQuery.value = ""
	})

	function threadLinks() {
		const query = mediaSearchQuery.value.trim().toLowerCase()
		return (context.messages.data || [])
			.flatMap((m) => (m.content || "").match(/(https?:\/\/[^\s]+|www\.[^\s]+)/gi) || [])
			.map((url) => ({ url, href: /^https?:\/\//i.test(url) ? url : "https://" + url }))
			.filter((item) => !query || item.url.toLowerCase().includes(query))
	}

	function threadFiles() {
		const query = mediaSearchQuery.value.trim().toLowerCase()
		return (context.messages.data || []).filter(
			(m) => m.message_type === "File" && (!query || (m.file_name || "").toLowerCase().includes(query)),
		)
	}

	function fileExtensionLabel(item) {
		const name = (item && item.file_name) || ""
		const dot = name.lastIndexOf(".")
		return dot === -1 ? "" : name.slice(dot + 1).toUpperCase()
	}

	return {
		selectedThread,
		draftMessage,
		uploadingFile,
		draftAttachments,
		openFilePicker,
		removeAttachment,
		formatFileSize,
		attachmentIcon,
		attachmentIconBg,
		attachmentIconColor,
		isImageFile,
		downloadFile,
		showFilePreviewDialog,
		previewFile,
		openFilePreview,
		mediaSearchQuery,
		mediaViewMode,
		fileExtensionLabel,
		showMembersDialog,
		showMediaDialog,
		showTemplatesDialog,
		showInlineTemplates,
		myMessageTemplates,
		mediaTab,
		showAddMemberDialog,
		newMemberEmail,
		newMemberPermission,
		isMentioning,
		filteredMentionMembers,
		insertMention,
		insertTemplate,
		formatMessageContent,
		currentThread,
		otherPartyName,
		threadTitle,
		threadCreatedLabel,
		threadListTime,
		threadListPreview,
		isPanelOpen,
		selectThread,
		closeThread,
		isPartnerAdmin,
		isCustomerAdmin,
		isAnyAdmin,
		isRowAdmin,
		activeMembers,
		addMember,
		makeAdmin,
		removeMember,
		memberRowOptions,
		sendMessage,
		sendMessageOnEnter,
		isMine,
		isGrouped,
		groupedMessages,
		formatMessageTime,
		formatDateDivider,
		formatFullDateTime,
		avatarTheme,
		threadLinks,
		threadFiles,
	}
}
