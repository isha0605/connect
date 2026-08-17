import { ref, computed, watch, onScopeDispose, nextTick } from "vue"
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

	// A private message needs no separate recipient picker: its audience is just whichever
	// thread members got @mentioned in the draft, resolved (and re-validated server-side —
	// see send_message) at send time rather than tracked as separate state.
	const privateMode = ref(false)

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
		fetchPinnedMessage()
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

	// A deleted message's sender already drops it from their own view right after the delete
	// call resolves (see deleteMessage) — this is purely for everyone else's open tabs.
	function handleMessageDeleted(payload) {
		if (payload.thread === selectedThread.value) context.messages.reload()
	}
	socket.on("connect_message_deleted", handleMessageDeleted)
	onScopeDispose(() => socket.off("connect_message_deleted", handleMessageDeleted))

	function handleMessageEdited(payload) {
		if (payload.thread === selectedThread.value) context.messages.reload()
	}
	socket.on("connect_message_edited", handleMessageEdited)
	onScopeDispose(() => socket.off("connect_message_edited", handleMessageEdited))

	// The pin/unpin call itself already updates the acting tab's own `pinnedMessage` — this is
	// purely for everyone else's open tabs, and carries the pinned message's fields directly in
	// the payload so those tabs don't need a round trip back to get_pinned_message.
	function handleThreadPinChanged(payload) {
		if (payload.thread !== selectedThread.value) return
		pinnedMessage.value = payload.pinned_message
			? {
					name: payload.pinned_message,
					sender: payload.sender,
					message_type: payload.message_type,
					content: payload.content,
					file_name: payload.file_name,
				}
			: null
	}
	socket.on("connect_thread_pin_changed", handleThreadPinChanged)
	onScopeDispose(() => socket.off("connect_thread_pin_changed", handleThreadPinChanged))

	// WhatsApp-style sticky date: an in-flow date divider (e.g. "9th August 2026" sitting
	// between two days' messages) is always fully visible — it's not floating over anything,
	// there's nothing to hide it *from*. The fade-on-idle only applies to whichever divider is
	// currently pinned at the top via `position: sticky` (i.e. its natural spot has scrolled
	// past, so it's now floating over the messages below it instead of sitting inline).
	//
	// `position: sticky` alone can't tell us *which* header is currently the stuck one — every
	// header reports the same `top: 0` once stuck, indistinguishable from "about to become
	// stuck". So each date-group gets an invisible sentinel marking where its header would sit
	// if it *weren't* sticky; once a sentinel scrolls above the container's own top edge, that
	// group's header is the one currently floating. Walking sentinels in DOM (= chronological)
	// order and keeping the last one that's passed gives the single currently-stuck group.
	const showStickyDate = ref(true)
	const stuckDateKey = ref<string | null>(null)
	let stickyDateHideTimer: ReturnType<typeof setTimeout> | null = null

	// Whether the pane should keep tracking the newest message. Turned back on every time we
	// deliberately jump to bottom (thread open, send, incoming realtime message); turned off the
	// moment the user scrolls away from the bottom themselves, so reading old messages isn't
	// fought by an unrelated message arriving elsewhere.
	let stickToBottom = true

	function isNearMessagesBottom(el: HTMLElement) {
		return el.scrollHeight - el.scrollTop - el.clientHeight < 80
	}

	function onMessagesScroll(event) {
		showStickyDate.value = true
		if (stickyDateHideTimer) clearTimeout(stickyDateHideTimer)
		stickyDateHideTimer = setTimeout(() => {
			showStickyDate.value = false
		}, 1200)

		const container = event && (event.currentTarget || event.target)
		if (!container) return
		stickToBottom = isNearMessagesBottom(container)

		const containerTop = container.getBoundingClientRect().top
		let stuck = null
		container.querySelectorAll("[data-date-sentinel]").forEach((el) => {
			if (el.getBoundingClientRect().top <= containerTop + 1) {
				stuck = el.getAttribute("data-date-sentinel")
			}
		})
		stuckDateKey.value = stuck
	}

	function isDateStuckAndIdle(item) {
		return !!item && item.dateKey === stuckDateKey.value && !showStickyDate.value
	}

	// Jump the message pane to the newest message — opening/switching a thread and sending a
	// message should always land on what was just written, not wherever the scroll happened to
	// be. A plain scrollTop=scrollHeight right after nextTick can still undershoot though:
	// avatars/image attachments that haven't finished loading yet grow the container a moment
	// later, leaving the "bottom" short of the real last message (looked like landing a whole day
	// early when the tail of the list is image-heavy). The ResizeObserver re-pins on every
	// subsequent layout change while stickToBottom holds, so a late-loading image can't strand
	// the scroll partway up.
	let messagesResizeObserver: ResizeObserver | null = null

	function scrollMessagesToBottom() {
		stickToBottom = true
		nextTick(() => {
			const el = document.querySelector('[data-component-id="messages-scroll"]') as HTMLElement | null
			if (!el) return
			el.scrollTop = el.scrollHeight

			if (!messagesResizeObserver) {
				const content = el.firstElementChild
				if (content) {
					messagesResizeObserver = new ResizeObserver(() => {
						if (stickToBottom) el.scrollTop = el.scrollHeight
					})
					messagesResizeObserver.observe(content)
				}
			}
		})
	}

	// `messages`' own filters are dynamically bound to selectedThread (see the page's resource
	// config), so Studio's resource layer *also* reloads it reactively on top of any explicit
	// .reload() call made below — racing two fetches and only scrolling after one of them would
	// leave the pane wherever the other one's re-render happened to land. Watching the data
	// itself sidesteps the race: it fires once, after whichever fetch actually lands last.
	watch(
		() => context.messages.data,
		() => scrollMessagesToBottom(),
	)

	onScopeDispose(() => {
		if (stickyDateHideTimer) clearTimeout(stickyDateHideTimer)
		messagesResizeObserver?.disconnect()
	})

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

	// Every "@word" anywhere in the text (not just a trailing in-progress one, unlike
	// mentionMatch) that matches a current member's email local-part — this is what turns
	// @mentions in the draft into the private message's actual recipient list.
	function extractMentionedMembers(text) {
		const names = new Set(((text || "").match(/@([^\s@]+)/g) || []).map((m) => m.slice(1).toLowerCase()))
		if (!names.size) return []
		return activeMembers().filter((m) => names.has((m.user || "").split("@")[0].toLowerCase()))
	}

	// Neutralizes text before it's interpolated into an HTML-component string (which renders
	// via v-html — nothing about the templating layer escapes it automatically). Needed for
	// any attacker-influenced text going into markup, e.g. a message-image's alt="{{ ... }}",
	// where file_name is whatever the uploader named their file.
	function escapeHtmlAttr(text) {
		const div = document.createElement("div")
		div.textContent = text || ""
		return div.innerHTML
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
		const timeText = item && item.is_edited ? "Edited · " + time : time
		const timeSpan =
			'<span style="float: right; margin-left: 8px; margin-top: 6px; margin-right: -6px; font-size: 9px; ' +
			'line-height: 12px; color: var(--ink-gray-5); white-space: nowrap;">' +
			timeText +
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

	function messageActionsOptions(item) {
		if (!item || !isMine(item.sender)) return []
		const onClick = item.isFileCluster ? () => confirmDeleteCluster(item) : () => confirmDeleteMessage(item)
		return [{ label: "Delete", icon: "lucide-trash-2", theme: "red", onClick }]
	}

	const showDeleteMessageDialog = ref(false)
	const messageToDelete = ref(null)
	const deletingMessage = ref(false)

	function confirmDeleteMessage(item) {
		messageToDelete.value = item
		showDeleteMessageDialog.value = true
	}

	async function deleteMessage() {
		if (!messageToDelete.value || deletingMessage.value) return
		deletingMessage.value = true
		try {
			await call("connect.api.delete_message", { message: messageToDelete.value.name })
			showDeleteMessageDialog.value = false
			messageToDelete.value = null
			context.messages.reload()
		} catch (e) {
			toast({
				title: "Could not delete message",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			deletingMessage.value = false
		}
	}

	// ---- Editing a message ----
	const showEditMessageDialog = ref(false)
	const messageToEdit = ref(null)
	const editMessageContent = ref("")
	const editingMessage = ref(false)

	function confirmEditMessage(item) {
		if (!item || item.isFileCluster || item.message_type !== "Text" || !isMine(item.sender)) return
		messageToEdit.value = item
		editMessageContent.value = item.content
		showEditMessageDialog.value = true
	}

	function closeEditMessageDialog() {
		showEditMessageDialog.value = false
		messageToEdit.value = null
		editMessageContent.value = ""
	}

	async function saveEditedMessage() {
		if (!messageToEdit.value || editingMessage.value) return
		const content = editMessageContent.value.trim()
		if (!content) return
		editingMessage.value = true
		try {
			await call("connect.api.edit_message", { message: messageToEdit.value.name, content })
			closeEditMessageDialog()
			context.messages.reload()
		} catch (e) {
			toast({
				title: "Could not edit message",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			editingMessage.value = false
		}
	}

	function saveEditedMessageOnEnter(event) {
		if (event && event.key === "Enter" && !event.shiftKey) {
			event.preventDefault()
			saveEditedMessage()
		}
	}

	// ---- Pinning a message ----
	// One pin at a time per thread (see connect.api.pin_message) — the currently pinned
	// message's own fields are kept here rather than re-derived from context.messages.data
	// since the pinned message can scroll out of the loaded window (200-message limit).
	const pinnedMessage = ref(null)

	async function fetchPinnedMessage() {
		if (!selectedThread.value) {
			pinnedMessage.value = null
			return
		}
		try {
			pinnedMessage.value = await call("connect.api.get_pinned_message", { thread: selectedThread.value })
		} catch (e) {
			pinnedMessage.value = null
		}
	}

	function isPinned(item) {
		return !!(pinnedMessage.value && item && pinnedMessage.value.name === item.name)
	}

	async function togglePinMessage(item) {
		if (!item || item.isFileCluster) return
		try {
			if (isPinned(item)) {
				await call("connect.api.unpin_message", { thread: selectedThread.value })
				pinnedMessage.value = null
			} else {
				await call("connect.api.pin_message", { message: item.name })
				await fetchPinnedMessage()
			}
		} catch (e) {
			toast({
				title: "Could not update pinned message",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		}
	}

	async function unpinMessage() {
		if (!selectedThread.value || !pinnedMessage.value) return
		try {
			await call("connect.api.unpin_message", { thread: selectedThread.value })
			pinnedMessage.value = null
		} catch (e) {
			toast({
				title: "Could not unpin message",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		}
	}

	function pinnedMessageLabel() {
		if (!pinnedMessage.value) return ""
		const sender = (pinnedMessage.value.sender || "").split("@")[0]
		const body =
			pinnedMessage.value.message_type === "File"
				? "📎 " + (pinnedMessage.value.file_name || "Attachment")
				: pinnedMessage.value.content
		return sender + ": " + body
	}

	function scrollToPinnedMessage() {
		if (!pinnedMessage.value) return
		const el = document.querySelector(`[data-message-id="${pinnedMessage.value.name}"]`)
		if (el) el.scrollIntoView({ behavior: "smooth", block: "center" })
	}

	// ---- Deleting a whole file cluster ----
	// A cluster is a synthetic client-side grouping (see clusterFileMessages) of several real
	// Connect Message docs sent close together — there's one delete trigger for the group, but
	// deletion itself is still per-file: the dialog lists every file with its own checkbox
	// (checked = will be deleted, all checked by default) rather than an all-or-nothing wipe.
	const showDeleteClusterDialog = ref(false)
	const clusterToDelete = ref(null)
	const clusterFilesToDelete = ref(new Set())
	const deletingCluster = ref(false)

	function confirmDeleteCluster(item) {
		clusterToDelete.value = item
		clusterFilesToDelete.value = new Set((item.files || []).map((f) => f.name))
		showDeleteClusterDialog.value = true
	}

	function isClusterFileMarkedForDeletion(file) {
		return clusterFilesToDelete.value.has(file.name)
	}

	function toggleClusterFileForDeletion(file) {
		const next = new Set(clusterFilesToDelete.value)
		if (next.has(file.name)) next.delete(file.name)
		else next.add(file.name)
		clusterFilesToDelete.value = next
	}

	async function deleteSelectedClusterFiles() {
		if (!clusterToDelete.value || deletingCluster.value) return
		const names = [...clusterFilesToDelete.value]
		if (!names.length) {
			showDeleteClusterDialog.value = false
			clusterToDelete.value = null
			return
		}
		deletingCluster.value = true
		try {
			for (const name of names) {
				await call("connect.api.delete_message", { message: name })
			}
			showDeleteClusterDialog.value = false
			clusterToDelete.value = null
			context.messages.reload()
		} catch (e) {
			toast({
				title: "Could not delete files",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			deletingCluster.value = false
		}
	}

	async function sendMessage() {
		if (!selectedThread.value || uploadingFile.value) return
		const readyAttachments = draftAttachments.value.filter((a) => a.file_url)
		const content = draftMessage.value.trim()
		if (!content && !readyAttachments.length) return

		// Validated (and the draft left untouched) before anything is cleared or sent — a
		// private toggle with no resolvable @mention shouldn't silently send publicly, or
		// silently eat what was typed.
		let recipients = null
		if (privateMode.value) {
			if (!content) {
				toast({
					title: "Type a message mentioning who should see it",
					icon: "x-circle",
					iconClasses: "text-red-600",
				})
				return
			}
			const me = context.myContext.data && context.myContext.data.user
			recipients = [...new Set(extractMentionedMembers(content).map((m) => m.user))].filter((u) => u !== me)
			if (!recipients.length) {
				toast({
					title: "Mention at least one person to send privately",
					text: "e.g. @" + ((me || "").split("@")[0] || "name"),
					icon: "x-circle",
					iconClasses: "text-red-600",
				})
				return
			}
		}

		const thread = selectedThread.value
		draftMessage.value = ""
		draftAttachments.value = []
		privateMode.value = false

		try {
			if (content) {
				await call("connect.api.send_message", {
					thread,
					content,
					is_private: !!recipients,
					recipients,
				})
			}
			for (const a of readyAttachments) {
				await call("connect.api.send_message", {
					thread,
					content: "",
					file_url: a.file_url,
					file_name: a.file_name,
					file_type: a.file_type,
					file_size: a.file_size,
					is_private: !!recipients,
					recipients,
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
	//
	// Fetched as a blob rather than navigating `<a>` straight to item.attachment: private
	// files are served through Frappe's download route, which sets Content-Disposition to
	// the deduped on-disk filename (a random suffix gets appended whenever a same-named file
	// already exists). That header wins over the anchor's `download` attribute in Chrome, so
	// a direct link leaks the disk name. A blob: URL has no Content-Disposition, so `download`
	// is all that's left to decide the saved filename.
	async function downloadFile(item, event) {
		if (event) {
			event.preventDefault()
			event.stopPropagation()
		}
		if (!item || !item.attachment) return
		try {
			const response = await fetch(item.attachment)
			if (!response.ok) throw new Error("Download failed")
			const blob = await response.blob()
			const blobUrl = URL.createObjectURL(blob)
			const link = document.createElement("a")
			link.href = blobUrl
			link.download = item.file_name || ""
			document.body.appendChild(link)
			link.click()
			link.remove()
			URL.revokeObjectURL(blobUrl)
		} catch (e) {
			toast({
				title: "Could not download file",
				text: e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		}
	}

	// ---- File preview dialog ----
	// A plain fixed overlay (not frappe-ui's Dialog) so it can truly cover the whole viewport
	// edge-to-edge with no scroller — Dialog always wraps content in a margined, capped-width
	// box with its own scrollable backdrop, neither of which is overridable via props. Escape-
	// to-close is normally Dialog's job, so it's reimplemented here.
	const showFilePreviewDialog = ref(false)
	const previewFile = ref(null)

	function openFilePreview(item) {
		previewFile.value = item
		showFilePreviewDialog.value = true
	}

	function handleFilePreviewKeydown(event: KeyboardEvent) {
		if (event.key === "Escape" && showFilePreviewDialog.value) {
			showFilePreviewDialog.value = false
		}
	}
	window.addEventListener("keydown", handleFilePreviewKeydown)
	onScopeDispose(() => window.removeEventListener("keydown", handleFilePreviewKeydown))

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

	// "Partner"/"Customer" tag next to a message's sender — only meaningful pointed at the
	// *other* side, so a customer sees who on the partner side is talking and vice versa;
	// same-side colleagues (and your own messages) never get tagged with your own side.
	// Reads the viewer's own side off the same per-thread membership list senderSide() uses
	// (not myContext.data.partner/.customer, which is *company*-level membership) — a user can
	// be a thread member without also having a Connect Customer/Partner Member row, and in that
	// case myContext's side fields are both null, which would show every badge instead of none.
	function myOwnSide() {
		return senderSide({ sender: context.myContext.data && context.myContext.data.user })
	}

	function senderSide(item) {
		const sender = item && item.sender
		const member = (context.threadMembers.data || []).find((m) => m.user === sender)
		return member ? member.side : null
	}

	function showSenderSideBadge(item) {
		const side = senderSide(item)
		return !!side && side !== myOwnSide()
	}

	function senderSideBadgeTheme(item) {
		return senderSide(item) === "Customer" ? "amber" : "violet"
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

	// Mirrors the media search box's focus treatment (see media-search-box's CSS) on the
	// composer: the pill is a container wrapping a ghost TextInput, so there's no single
	// element a :focus-within rule could live on — the inner input reports focus up instead.
	const composerFocused = ref(false)

	// ---- Media ----
	const mediaSearchQuery = ref("")
	const mediaViewMode = ref("list")

	// The Files/Links search box is a raw HTML block (see media-search-box in the JSON) rather
	// than frappe-ui's TextInput — that component never exposes its actual <input> to outside
	// styling, only a wrapper div, so there's no way to get the icon to render inside the same
	// box as the text. A plain <input> lets a real `<style>` block own :hover/:focus directly.
	// Since v-html renders it outside Vue's reactivity, it's wired to app state by hand: typing
	// calls a function stashed on `window` (inline `oninput` only has access to global scope),
	// and switching tabs reaches back into the DOM to clear/relabel it.
	function updateMediaSearchQuery(value) {
		mediaSearchQuery.value = value
	}
	if (typeof window !== "undefined") {
		window.__connectMediaSearchInput = updateMediaSearchQuery
	}

	// a leftover query from the Files tab would otherwise silently filter out every
	// link (and vice versa) since both tabs share one search box
	watch(mediaTab, () => {
		mediaSearchQuery.value = ""
		nextTick(() => {
			const el = document.getElementById("cnct-media-search-input")
			if (el) {
				el.value = ""
				el.placeholder = mediaTab.value === "Files" ? "Search files..." : "Search links..."
			}
		})
	})

	function threadLinks() {
		const query = mediaSearchQuery.value.trim().toLowerCase()
		return (context.messages.data || [])
			.flatMap((m) =>
				((m.content || "").match(/(https?:\/\/[^\s]+|www\.[^\s]+)/gi) || []).map((url) => ({ url, message: m })),
			)
			.map(({ url, message }) => {
				const href = /^https?:\/\//i.test(url) ? url : "https://" + url
				let domain = url
				try {
					domain = new URL(href).hostname
				} catch (e) {
					// leave the raw matched text as the domain if it doesn't parse
				}
				const label = domain.replace(/^www\./, "").split(".")[0]
				const title = label ? label.charAt(0).toUpperCase() + label.slice(1) : domain
				return { url, href, domain, title, sender: message.sender, creation: message.creation }
			})
			.filter(
				(item) =>
					!query || item.url.toLowerCase().includes(query) || item.title.toLowerCase().includes(query),
			)
	}

	function openLink(item) {
		if (item && item.href) window.open(item.href, "_blank", "noopener")
	}

	// mirrors formatDateDivider's ordinal-date fallback, but names the last 6 days by
	// weekday instead — matches how the Links card list shows "Tuesday" rather than a date
	function formatRelativeDay(item) {
		const d = new Date(item.creation)
		const startOfDay = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
		const diffDays = Math.round((startOfDay(new Date()) - startOfDay(d)) / 86400000)
		if (diffDays === 0) return "Today"
		if (diffDays === 1) return "Yesterday"
		if (diffDays > 1 && diffDays < 7) return d.toLocaleDateString("en-US", { weekday: "long" })
		return formatOrdinalDate(d)
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
		composerFocused,
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
		privateMode,
		formatMessageContent,
		escapeHtmlAttr,
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
		messageActionsOptions,
		showDeleteMessageDialog,
		messageToDelete,
		deletingMessage,
		deleteMessage,
		showEditMessageDialog,
		editMessageContent,
		editingMessage,
		confirmEditMessage,
		closeEditMessageDialog,
		saveEditedMessage,
		saveEditedMessageOnEnter,
		pinnedMessage,
		isPinned,
		togglePinMessage,
		unpinMessage,
		pinnedMessageLabel,
		scrollToPinnedMessage,
		showDeleteClusterDialog,
		clusterToDelete,
		deletingCluster,
		isClusterFileMarkedForDeletion,
		toggleClusterFileForDeletion,
		deleteSelectedClusterFiles,
		sendMessage,
		sendMessageOnEnter,
		isMine,
		senderSide,
		showSenderSideBadge,
		senderSideBadgeTheme,
		isGrouped,
		groupedMessages,
		formatMessageTime,
		onMessagesScroll,
		isDateStuckAndIdle,
		formatDateDivider,
		formatFullDateTime,
		avatarTheme,
		threadLinks,
		threadFiles,
		openLink,
		formatRelativeDay,
	}
}
