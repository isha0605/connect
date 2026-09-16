import { ref, computed, watch, onScopeDispose, nextTick } from "vue"
import { toast, call, useFileUpload, initSocket, setConfig } from "frappe-ui"
import RAW_EMOJIS from "./emojis.json"

export default function setup(context) {
	// ==============================================================================================
	// Wired to the real Connect backend via the "resources" declared in messaging.json (myContext,
	// myThreads, messages, threadMembers, threadAdmins, memberProfiles, partnerInfo, myShortlist) —
	// each shows up on `context` under its resource_name. Studio merges the final template context
	// as {...resources, ...whatever setup() returns}, so none of those names are returned below:
	// doing so would shadow the live resource with whatever setup() last computed.
	//
	// This mirrors studio/connect_2/studio_page/messaging/messaging.ts (the other, already-wired
	// chat page) wherever this page's UI has the same feature — see that file for the DM/templates/
	// mentions/profile-settings machinery this page's UI has no hooks for, so none of it is ported.
	// Two things this page's UI has that connect_2's doesn't (the partner logo/response-time header
	// stats and the shortlist toggle) are wired against connect.api.partner.get_partner_preview and
	// connect.api.customer.*_shortlist instead.
	// ==============================================================================================

	// ---- State ----
	const selectedThread = ref("")
	const draftMessage = ref("")
	const draftAttachments = ref([])
	let nextAttachmentId = 1
	const togglingShortlist = ref(false)
	const showMembersDialog = ref(false)
	const showMediaDialog = ref(false)
	// Declared here (not down by the rest of the pinning code) because selectThread(), invoked
	// synchronously below via the immediate watcher whenever context.myThreads.data is already
	// populated (e.g. cached from a prior load), calls fetchPinnedMessage() before setup() reaches
	// that section — referencing a `const` declared later throws (temporal dead zone), which was
	// silently aborting the rest of setup() and everything derived from it, including the emoji list.
	const pinnedMessage = ref(null)

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

	// Partner/Customer autoname by their raw company name, so the docname itself carries
	// whatever legal suffix the company registered under — strip it for display only, since
	// the underlying docname (used for filters, shortlist matching, etc.) must stay untouched.
	function displayCompanyName(name) {
		if (!name) return name
		return name.replace(/\s*,?\s*(private\s+limited|pvt\.?\s*ltd\.?)\s*$/i, "").trim()
	}

	// Threads carry the other side's company name directly (Partner/Customer both
	// autoname by their display name), so no extra lookup is needed here.
	function otherPartyName(thread) {
		return displayCompanyName(amPartner() ? thread.customer : thread.partner)
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

	// Customer has no logo field yet, so only the customer-viewing-partner direction has an
	// image to show; a partner viewing a customer thread always falls back to the Avatar's
	// own initials rendering (driven by the `label` prop already bound alongside this).
	function threadListLogo(thread) {
		return amPartner() ? "" : (thread && thread.partner_logo) || ""
	}

	function threadListPreview(thread) {
		if (!thread || !thread.last_message) return "No messages yet"
		const me = context.myContext.data && context.myContext.data.user
		const sender = thread.last_message_sender
		let label = sender === me ? "You" : (sender || "").split("@")[0]
		if (label && label !== "You") label = label.charAt(0).toUpperCase() + label.slice(1)
		return (label ? label + ": " : "") + thread.last_message
	}

	function isPanelOpen() {
		return showMembersDialog.value || showMediaDialog.value
	}

	function toggleMembersPanel() {
		showMediaDialog.value = false
		showMembersDialog.value = !showMembersDialog.value
	}

	function toggleMediaPanel() {
		showMembersDialog.value = false
		showMediaDialog.value = !showMediaDialog.value
	}

	function selectThread(item) {
		const name = typeof item === "string" ? item : item.name
		selectedThread.value = name

		context.messages.filters = { thread: name }
		context.messages.reload()
		context.threadMembers.filters = { thread: name }
		context.threadMembers.reload()
		context.threadAdmins.params = { thread: name }
		context.threadAdmins.reload()
		context.memberProfiles.params = { thread: name }
		context.memberProfiles.reload()
		context.partnerInfo.params = { partner: currentThread().partner }
		context.partnerInfo.reload()
		call("connect.api.threads.mark_thread_read", { thread: name })
			.then(() => context.myThreads.reload())
			.catch(() => {})

		showMembersDialog.value = false
		showMediaDialog.value = false
		fetchPinnedMessage()
	}

	// Auto-select the top conversation (myThreads is server-sorted by last activity) as soon as
	// the inbox list loads, so the pane isn't left on "Select a conversation" on first render.
	// Only fires while nothing is selected yet — later reloads (new message, send, etc.) must
	// never yank the user back to the top thread.
	watch(
		() => context.myThreads.data,
		(threads) => {
			if (!selectedThread.value && threads && threads.length) selectThread(threads[0])
		},
		{ immediate: true },
	)

	// ---- Realtime ----
	// A dedicated connection for this page rather than reusing Studio's own — page scripts run
	// in a detached effect scope with no component instance, so the socket Studio provides via
	// Vue's provide()/inject() further up the tree isn't reachable here. Mirrors connect_2's
	// wiring exactly, minus the DM-only handlers this page has no DM UI for.
	if (!(window as any).site_name) (window as any).site_name = window.location.hostname
	const socket = initSocket()

	// Without this, useFileUpload's client-side size check has no limit to compare against and
	// silently lets oversized files through to the raw upload, which then fails as an opaque
	// network error instead of an upfront, readable message. Studio-rendered pages don't get a
	// window.frappe.boot object (unlike desk), so the limit has to be fetched rather than read
	// off boot data.
	call("frappe.core.api.file.get_max_file_size").then((maxFileSize) => {
		if (maxFileSize) setConfig("maxFileSize", maxFileSize)
	})

	function handleNewMessage(payload) {
		if (payload.thread === selectedThread.value) context.messages.reload()
		context.myThreads.reload()
	}
	socket.on("connect_new_message", handleNewMessage)
	onScopeDispose(() => socket.off("connect_new_message", handleNewMessage))

	// A deleted/edited message's own sender already reflects the change locally right after the
	// call resolves — these are purely for everyone else's open tabs.
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
	// purely for everyone else's open tabs.
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

	// Jump the message pane to the newest message on thread switch / send / incoming message.
	// A plain scrollTop=scrollHeight right after nextTick can undershoot while a late-loading
	// attachment image is still growing the container, so a ResizeObserver keeps re-pinning
	// until the user deliberately scrolls away.
	let stickToBottom = true
	let messagesResizeObserver: ResizeObserver | null = null

	function isNearMessagesBottom(el: HTMLElement) {
		return el.scrollHeight - el.scrollTop - el.clientHeight < 80
	}

	function onMessagesScroll(event) {
		const container = event && (event.currentTarget || event.target)
		if (container) stickToBottom = isNearMessagesBottom(container)
	}

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
	watch(() => context.messages.data, scrollMessagesToBottom)
	onScopeDispose(() => messagesResizeObserver?.disconnect())

	// ---- Conversation header stats ----
	function activeMemberCount() {
		return activeMembers().length
	}

	function activeMembers() {
		return (context.threadMembers.data || []).filter((m) => !m.is_removed)
	}

	// get_partner_preview returns a single object (not a list), unlike the mock this replaced.
	function currentPartner() {
		return context.partnerInfo.data || null
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
			await context.myShortlist.reload()
		} catch (e) {
			toast({
				title: "Could not update shortlist",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			togglingShortlist.value = false
		}
	}

	// No hiring flow exists yet anywhere in the app — the button just acknowledges the click.
	function hirePartner() {
		toast({ title: "Hire flow coming soon", icon: "check", iconClasses: "text-green-600" })
	}

	// No scheduling flow exists yet anywhere in the app — the button just acknowledges the click.
	function bookSlot() {
		toast({ title: "Booking flow coming soon", icon: "check", iconClasses: "text-green-600" })
	}

	function closeConversation() {
		if (!window.confirm("Close this conversation?")) return
		call("connect.api.threads.close_thread", { thread: selectedThread.value })
			.then(() => {
				context.myThreads.reload()
				context.messages.reload()
				toast({ title: "Conversation closed", icon: "check", iconClasses: "text-green-600" })
			})
			.catch((e) => {
				toast({
					title: "Could not close conversation",
					text: e.messages ? e.messages[0] : e.message,
					icon: "x-circle",
					iconClasses: "text-red-600",
				})
			})
	}

	// ---- Admin checks (Members panel) ----
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

	// ---- Members panel ----
	const showAddMemberDialog = ref(false)
	const newMemberEmail = ref("")
	const newMemberPermission = ref("Write")

	function addMember() {
		if (!newMemberEmail.value) {
			toast({ title: "Enter an email", icon: "x-circle", iconClasses: "text-red-600" })
			return
		}
		const side = amPartner() ? "Partner" : "Customer"
		call("connect.api.threads.add_thread_member", {
			thread: selectedThread.value,
			email: newMemberEmail.value,
			side,
			permission: newMemberPermission.value,
		})
			.then((data) => {
				showAddMemberDialog.value = false
				newMemberEmail.value = ""
				newMemberPermission.value = "Write"
				context.threadMembers.reload()
				context.memberProfiles.reload()
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
		call("connect.api.threads.make_thread_admin", { thread: selectedThread.value, member: item.name })
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
		call("connect.api.threads.remove_thread_member", { thread: selectedThread.value, member: item.name })
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
			{ label: "Remove from chat", icon: "lucide-user-minus", theme: "red", disabled, onClick: () => removeMember(item) },
		]
	}

	// ---- Sender identity (hover card + avatars) ----
	function memberProfile(email) {
		const profiles = context.memberProfiles.data || []
		return profiles.find((p) => p.name === email) || null
	}

	function capitalizeName(name) {
		return name ? name.charAt(0).toUpperCase() + name.slice(1) : name
	}

	function memberDisplayName(email) {
		const profile = memberProfile(email)
		if (profile && profile.full_name) return capitalizeName(profile.full_name)
		const local = (email || "").split("@")[0]
		return local ? capitalizeName(local) : email || ""
	}

	function memberEmail(email) {
		return email || ""
	}

	function memberImage(email) {
		const profile = memberProfile(email)
		return (profile && profile.user_image) || ""
	}

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

	// "Partner"/"Customer" tag next to a message's sender — only meaningful pointed at the
	// *other* side, so a customer sees who on the partner side is talking and vice versa.
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

	const hoveredSender = ref(null)

	function openSenderCard(email) {
		hoveredSender.value = email
	}

	function closeSenderCard() {
		hoveredSender.value = null
	}

	function isSenderCardOpen(email) {
		return hoveredSender.value === email
	}

	// ---- Requirement → Company card ----
	// A "Requirement" message stores its snapshot as a JSON blob in `content` (see
	// connect.api.messages.send_message), not the {company_name, industry, employee_count} shape
	// the company-card block reads — this reshapes it into that view model at read time so the
	// existing card renders unchanged. There's no server-side "Company" message_type; this is a
	// display-only relabel, same trick clusterFileMessages below uses for grouping file messages.
	function parseRequirementContent(item) {
		try {
			return JSON.parse((item && item.content) || "{}") || {}
		} catch (e) {
			return {}
		}
	}

	function requirementToCompanyCard(item) {
		const req = parseRequirementContent(item)
		return {
			...item,
			message_type: "Company",
			company_name: req.company_name || "",
			industry: req.industry || "",
			employee_count: req.company_size || "",
		}
	}

	// ---- Messages ----
	// messages is a Document List resource sorted creation DESC (see messaging.json) — sorting by
	// creation ascending here (rather than a blind .reverse()) stays correct regardless of the
	// resource's own sort order or how ties resolve.
	function currentMessages() {
		return [...(context.messages.data || [])]
			.sort((a, b) => new Date(a.creation).getTime() - new Date(b.creation).getTime())
			.map((item) => (item.message_type === "Requirement" ? requirementToCompanyCard(item) : item))
	}

	// consecutive files from the same sender, sent within 2 minutes of each other, are merged
	// into one synthetic "cluster" item so they render as a single wrapped row with one time
	// underneath instead of a separate full-width row per file.
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
	// date divider rendered once per section instead of a divider re-checked per message.
	const groupedMessages = computed(() => {
		const groups = []
		let lastKey = null
		for (const item of currentMessages()) {
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

	function formatOrdinalDate(date) {
		const day = date.getDate()
		const suffix =
			day % 10 === 1 && day !== 11 ? "st" : day % 10 === 2 && day !== 12 ? "nd" : day % 10 === 3 && day !== 13 ? "rd" : "th"
		return day + suffix + " " + date.toLocaleDateString("en-US", { month: "long", year: "numeric" })
	}

	function threadCreatedLabel() {
		const t = currentThread()
		if (!t.creation) return ""
		const firstMessage = currentMessages()[0]
		if (firstMessage && isMine(firstMessage.sender)) return "You started this conversation"
		return "Thread created on " + formatOrdinalDate(new Date(t.creation))
	}

	function formatFullDateTime(item) {
		const d = new Date(item.creation)
		const timeStr = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase()
		return formatOrdinalDate(d) + ", " + timeStr
	}

	function formatDateDivider(item) {
		const d = new Date(item.creation)
		const now = new Date()
		if (d.toDateString() === now.toDateString()) return "Today"
		const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000)
		if (d.toDateString() === yesterday.toDateString()) return "Yesterday"
		return formatOrdinalDate(d)
	}

	// Neutralizes text before it's interpolated into an HTML-component string (v-html renders it
	// with nothing escaping it automatically) — needed for file_name, which is whatever the
	// uploader named their file, going into an <img alt="...">.
	function escapeHtmlAttr(text) {
		const div = document.createElement("div")
		div.textContent = text || ""
		return div.innerHTML
	}

	function isMine(sender) {
		return sender === (context.myContext.data && context.myContext.data.user)
	}

	function formatMessageTime(item) {
		const time = new Date(item.creation).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase()
		return item.is_edited ? "Edited · " + time : time
	}

	// ---- Editing a message ----
	// Editing happens in the composer itself (matching Telegram/WhatsApp Web) rather than a
	// popup: messageToEdit gates an "Editing message" strip above the input and repurposes
	// draftMessage as the edit buffer, so Enter/Send both branch into saveEditedMessage instead
	// of sendMessage while it's set.
	const messageToEdit = ref(null)
	const editingMessage = ref(false)

	function confirmEditMessage(item) {
		if (!item || item.isFileCluster || item.message_type !== "Text" || !isMine(item.sender)) return
		messageToEdit.value = item
		draftMessage.value = item.content
		nextTick(() => {
			const el = document.querySelector('[data-component-id="message-input"]') as HTMLTextAreaElement | null
			el?.focus()
		})
	}

	function cancelEditMessage() {
		messageToEdit.value = null
		draftMessage.value = ""
	}

	// The backend enforces edit/delete ownership via Frappe's own permission system
	// (has_message_permission) — a denied attempt surfaces as a generic PermissionError with no
	// specific message, so swap in our own wording for that one case.
	function permissionAwareErrorText(e, deniedText) {
		if (e.exc_type === "PermissionError") return deniedText
		return e.messages ? e.messages[0] : e.message
	}

	async function saveEditedMessage() {
		if (!messageToEdit.value || editingMessage.value) return
		const content = draftMessage.value.trim()
		if (!content) return
		editingMessage.value = true
		try {
			await call("connect.api.messages.edit_message", { message: messageToEdit.value.name, content })
			messageToEdit.value = null
			draftMessage.value = ""
			context.messages.reload()
		} catch (e) {
			toast({
				title: "Could not edit message",
				text: permissionAwareErrorText(e, "You don't have permission to edit this message"),
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			editingMessage.value = false
		}
	}

	// ---- Deleting a message ----
	async function deleteMessage(item) {
		if (!item || !window.confirm("Delete this message?")) return
		try {
			await call("connect.api.messages.delete_message", { message: item.name })
			context.messages.reload()
		} catch (e) {
			toast({
				title: "Could not delete message",
				text: permissionAwareErrorText(e, "You don't have permission to delete this message"),
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		}
	}

	// ---- Deleting a whole file cluster ----
	// A cluster is a synthetic client-side grouping of several messages sent close together —
	// deleting the group deletes every file message it contains.
	async function deleteCluster(item) {
		const files = (item && item.files) || []
		if (!files.length) return
		const label = files.length === 1 ? "this file" : `these ${files.length} files`
		if (!window.confirm(`Delete ${label}?`)) return
		try {
			for (const file of files) {
				await call("connect.api.messages.delete_message", { message: file.name })
			}
			context.messages.reload()
		} catch (e) {
			toast({
				title: "Could not delete files",
				text: permissionAwareErrorText(e, "You don't have permission to delete one or more of these files"),
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		}
	}

	// ---- Pinning a message ----
	// One pin at a time per thread (see connect.api.messages.pin_message). pinnedMessage itself is
	// declared up in State — see the comment there for why.

	async function fetchPinnedMessage() {
		if (!selectedThread.value) {
			pinnedMessage.value = null
			return
		}
		try {
			pinnedMessage.value = await call("connect.api.messages.get_pinned_message", { thread: selectedThread.value })
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
				await call("connect.api.messages.unpin_message", { thread: selectedThread.value })
				pinnedMessage.value = null
			} else {
				await call("connect.api.messages.pin_message", { message: item.name })
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
			await call("connect.api.messages.unpin_message", { thread: selectedThread.value })
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
		let body = pinnedMessage.value.content
		if (pinnedMessage.value.message_type === "File") body = "📎 " + (pinnedMessage.value.file_name || "Attachment")
		else if (pinnedMessage.value.message_type === "Requirement") body = "Company details"
		return sender + ": " + body
	}

	function scrollToPinnedMessage() {
		if (!pinnedMessage.value) return
		const el = document.querySelector(`[data-message-id="${pinnedMessage.value.name}"]`)
		if (el) el.scrollIntoView({ behavior: "smooth", block: "center" })
	}

	// ---- Per-message action menus ----
	function messageActionsOptions(item) {
		if (!item || !isMine(item.sender)) return []
		const options = []
		if (!item.isFileCluster && item.message_type === "Text") {
			options.push({ label: "Edit", icon: "lucide-pencil", onClick: () => confirmEditMessage(item) })
		}
		if (!item.isFileCluster) {
			options.push({
				label: isPinned(item) ? "Unpin" : "Pin",
				icon: isPinned(item) ? "lucide-pin-off" : "lucide-pin",
				onClick: () => togglePinMessage(item),
			})
		}
		const onDelete = item.isFileCluster ? () => deleteCluster(item) : () => deleteMessage(item)
		options.push({ label: "Delete", icon: "lucide-trash-2", theme: "red", onClick: onDelete })
		return options
	}

	// Menu for someone else's message — just Pin/Unpin, since edit/delete are sender-only.
	function otherMessageActionsOptions(item) {
		if (!item || item.isFileCluster) return []
		return [
			{ label: isPinned(item) ? "Unpin" : "Pin", icon: isPinned(item) ? "lucide-pin-off" : "lucide-pin", onClick: () => togglePinMessage(item) },
		]
	}

	// ---- Composer / attachments ----
	const uploadingFile = computed(() => draftAttachments.value.some((a) => a.uploading))

	// picking files happens through a throwaway <input>, created on demand — Studio's
	// component set has no file-picker element. Multiple files can be picked at once.
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

	// Uploaded ahead of Send so the composer can show a live progress state and a remove
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
			upload_endpoint: "/api/method/connect.api.attachments.upload_chat_attachment",
			params: { thread: selectedThread.value },
		})
			.then((data) => {
				const current = draftAttachments.value.find((a) => a.id === id)
				if (!current) {
					// removed while it was still uploading — clean up the now-orphaned file
					call("connect.api.attachments.remove_chat_attachment", { file_url: data.file_url }).catch(() => {})
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
			call("connect.api.attachments.remove_chat_attachment", { file_url: item.file_url }).catch((e) => {
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

	// A wrapping flex row with no explicit width has no reliable way to shrink to "the width of
	// its widest wrapped line" across browsers, so the exact pixel width is computed by hand,
	// mirroring the same greedy left-to-right packing flex-wrap does.
	function clusterRowWidth(dataItem) {
		const files = (dataItem && dataItem.files) || []
		if (!files.length) return "0px"
		const widths = files.map((f) => (isImageFile(f) ? 280 : 220))
		const gap = 6
		const maxLineWidth = 446
		let rows = [[]]
		let currentWidth = 0
		for (const w of widths) {
			const row = rows[rows.length - 1]
			const addedWidth = row.length ? w + gap : w
			if (row.length && currentWidth + addedWidth > maxLineWidth) {
				rows.push([w])
				currentWidth = w
			} else {
				row.push(w)
				currentWidth += addedWidth
			}
		}
		const widest = Math.max(...rows.map((row) => row.reduce((sum, w, i) => sum + w + (i ? gap : 0), 0)))
		return Math.min(widest, maxLineWidth) + "px"
	}

	// window.open(url, "_blank") flashes a new tab open-then-closed for URLs that trigger a
	// direct download — an <a download> click saves the file in place instead. Fetched as a blob
	// rather than navigating straight to item.attachment: private files are served through
	// Frappe's download route, which sets Content-Disposition to the deduped on-disk filename,
	// and that header wins over the anchor's `download` attribute in Chrome.
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
			link.download = item.file_name || "download"
			document.body.appendChild(link)
			link.click()
			link.remove()
			URL.revokeObjectURL(blobUrl)
		} catch (e) {
			toast({ title: "Could not download file", text: e.message, icon: "x-circle", iconClasses: "text-red-600" })
		}
	}

	// ---- File preview dialog ----
	const showFilePreviewDialog = ref(false)
	const previewFile = ref(null)

	function openFilePreview(item) {
		previewFile.value = item
		showFilePreviewDialog.value = true
	}

	function handleFilePreviewKeydown(event: KeyboardEvent) {
		if (event.key === "Escape" && showFilePreviewDialog.value) showFilePreviewDialog.value = false
	}
	window.addEventListener("keydown", handleFilePreviewKeydown)
	onScopeDispose(() => window.removeEventListener("keydown", handleFilePreviewKeydown))

	async function sendMessage() {
		if (!selectedThread.value || uploadingFile.value) return
		if (messageToEdit.value) {
			await saveEditedMessage()
			return
		}
		const readyAttachments = draftAttachments.value.filter((a) => a.file_url)
		const content = draftMessage.value.trim()
		if (!content && !readyAttachments.length) return

		const thread = selectedThread.value
		draftMessage.value = ""
		draftAttachments.value = []

		try {
			if (content) {
				await call("connect.api.messages.send_message", { thread, content })
			}
			for (const a of readyAttachments) {
				await call("connect.api.messages.send_message", {
					thread,
					content: "",
					file_url: a.file_url,
					file_name: a.file_name,
					file_type: a.file_type,
					file_size: a.file_size,
				})
			}
			context.messages.reload()
			context.myThreads.reload()
		} catch (e) {
			// A multi-part send (text + attachments) can partially succeed before one part fails —
			// reload so the sender's own view reflects whatever actually went through, rather than
			// looking empty until something else triggers a refresh.
			context.messages.reload()
			context.myThreads.reload()
			toast({
				title: "Could not send message",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		}
	}

	function sendMessageOnEnter(event) {
		if (!event) return
		if (event.key === "Escape" && messageToEdit.value) {
			event.preventDefault()
			cancelEditMessage()
			return
		}
		if (event.key === "Enter" && !event.shiftKey) {
			event.preventDefault()
			sendMessage()
		}
	}

	// The composer grows with the message the same way Slack's does. Textarea has no built-in
	// auto-grow, so height is measured and set by hand on every content change.
	function autoResizeComposer() {
		const el = document.querySelector('[data-component-id="message-input"]') as HTMLTextAreaElement | null
		if (!el) return
		el.style.height = "auto"
		el.style.height = el.scrollHeight + "px"
	}
	watch(draftMessage, () => nextTick(autoResizeComposer))

	// ---- Emoji picker ----
	// A small static grid, not a Studio/frappe-ui component — Studio's block set has no picker
	// primitive, and emoji themselves need no library (they're just characters), so the popover
	// is one more absolutely-positioned block (see emoji-picker in the JSON), same convention as
	// sender-hover-card and the members/media side panels.
	const showEmojiPicker = ref(false)
	const emojiSearchQuery = ref("")

	// The real emoji set frappe-ui itself ships (its TipTap editor's `:emoji` suggestion list) —
	// vendored as a local JSON file (see emojis.json) rather than importing from the package,
	// since that dataset isn't part of frappe-ui's public export surface (only the full TipTap
	// extension is, which needs a TipTap Editor instance, not this page's plain Textarea).
	if (!Array.isArray(RAW_EMOJIS)) {
		console.error("emojis.json did not import as an array — got:", RAW_EMOJIS)
	}
	const EMOJI_LIST = (Array.isArray(RAW_EMOJIS) ? RAW_EMOJIS : []).map((e: { name: string; emoji: string }) => ({
		char: e.emoji,
		name: e.name,
	}))

	function emojiList() {
		const query = emojiSearchQuery.value.trim().toLowerCase()
		if (!query) return EMOJI_LIST
		return EMOJI_LIST.filter((e) => e.name.includes(query))
	}

	function updateEmojiSearchQuery(value) {
		emojiSearchQuery.value = value
	}
	if (typeof window !== "undefined") {
		;(window as any).__connectEmojiSearchInput = updateEmojiSearchQuery
	}

	function toggleEmojiPicker() {
		showEmojiPicker.value = !showEmojiPicker.value
	}

	// Inserts at the textarea's actual cursor position (falling back to appending at the end if
	// the element isn't mounted yet) rather than always appending, so picking an emoji mid-message
	// doesn't jump it to the end of what's already been typed.
	function insertEmoji(char) {
		const el = document.querySelector('[data-component-id="message-input"]') as HTMLTextAreaElement | null
		const text = draftMessage.value || ""
		if (el && typeof el.selectionStart === "number") {
			const start = el.selectionStart
			const end = el.selectionEnd ?? start
			draftMessage.value = text.slice(0, start) + char + text.slice(end)
			nextTick(() => {
				el.focus()
				const pos = start + char.length
				el.setSelectionRange(pos, pos)
			})
		} else {
			draftMessage.value = text + char
		}
		showEmojiPicker.value = false
	}

	// Closes the picker on any click outside it or its trigger button — everything else on this
	// page (members/media panels) is closed by an explicit second click on its own toggle, but a
	// picker that stays pinned open until you hunt for the same tiny button again is bad enough
	// UX to warrant the one document-level listener on the page.
	function handleDocumentClickForEmojiPicker(event: MouseEvent) {
		if (!showEmojiPicker.value) return
		const target = event.target as Node
		const picker = document.querySelector('[data-component-id="emoji-picker"]')
		const trigger = document.querySelector('[data-component-id="composer-emoji-btn"]')
		if (picker && picker.contains(target)) return
		if (trigger && trigger.contains(target)) return
		showEmojiPicker.value = false
	}
	document.addEventListener("click", handleDocumentClickForEmojiPicker)
	onScopeDispose(() => document.removeEventListener("click", handleDocumentClickForEmojiPicker))

	// ---- Media panel (Files / Links) ----
	const mediaTab = ref("Files")
	const mediaSearchQuery = ref("")
	const mediaSortAscending = ref(false)

	function toggleMediaSort() {
		mediaSortAscending.value = !mediaSortAscending.value
	}

	function updateMediaSearchQuery(value) {
		mediaSearchQuery.value = value
	}
	if (typeof window !== "undefined") {
		;(window as any).__connectMediaSearchInput = updateMediaSearchQuery
	}

	watch(mediaTab, () => {
		mediaSearchQuery.value = ""
	})

	// Strips sentence punctuation a URL regex has no way to distinguish from part of the URL
	// itself (e.g. "check https://example.com." — the trailing period isn't part of the link).
	function stripTrailingPunctuation(url) {
		return url.replace(/[.,!?;:'"]+$/, "")
	}

	function threadLinks() {
		const query = mediaSearchQuery.value.trim().toLowerCase()
		return currentMessages()
			.flatMap((m) =>
				((m.content || "").match(/(https?:\/\/[^\s]+|www\.[^\s]+)/gi) || [])
					.map(stripTrailingPunctuation)
					.map((url) => ({ url, message: m })),
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
			.filter((item) => !query || item.url.toLowerCase().includes(query) || item.title.toLowerCase().includes(query))
			.sort((a, b) => {
				const diff = new Date(b.creation).getTime() - new Date(a.creation).getTime()
				return mediaSortAscending.value ? -diff : diff
			})
	}

	function openLink(item) {
		if (item && item.href) window.open(item.href, "_blank", "noopener")
	}

	// No backend for the scheduled-call feature yet (see the top-of-file note) — this stays
	// wired for whenever real Event-type items exist, but nothing currently produces one.
	function openEventLink(item) {
		if (item && item.event_url) window.open(item.event_url, "_blank", "noopener")
	}

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
		return currentMessages()
			.filter((m) => m.message_type === "File" && (!query || (m.file_name || "").toLowerCase().includes(query)))
			.sort((a, b) => {
				const diff = new Date(b.creation).getTime() - new Date(a.creation).getTime()
				return mediaSortAscending.value ? -diff : diff
			})
	}

	function fileExtensionLabel(item) {
		const name = (item && item.file_name) || ""
		const dot = name.lastIndexOf(".")
		return dot === -1 ? "" : name.slice(dot + 1).toUpperCase()
	}

	return {
		selectedThread,
		draftMessage,
		draftAttachments,
		togglingShortlist,
		showMembersDialog,
		showMediaDialog,
		isPanelOpen,
		toggleMembersPanel,
		toggleMediaPanel,
		threadList,
		currentThread,
		amPartner,
		otherPartyName,
		threadTitle,
		threadListTime,
		threadListPreview,
		threadListLogo,
		selectThread,
		onMessagesScroll,
		activeMemberCount,
		activeMembers,
		currentPartner,
		partnerLogo,
		responseTimeLabel,
		localTimeLabel,
		isShortlisted,
		toggleShortlist,
		hirePartner,
		bookSlot,
		closeConversation,
		isAnyAdmin,
		isRowAdmin,
		showAddMemberDialog,
		newMemberEmail,
		newMemberPermission,
		addMember,
		memberRowOptions,
		memberDisplayName,
		memberEmail,
		memberImage,
		avatarTheme,
		showSenderSideBadge,
		senderSideBadgeTheme,
		senderSide,
		openSenderCard,
		closeSenderCard,
		isSenderCardOpen,
		currentMessages,
		groupedMessages,
		escapeHtmlAttr,
		threadCreatedLabel,
		formatFullDateTime,
		isMine,
		formatMessageTime,
		messageToEdit,
		confirmEditMessage,
		cancelEditMessage,
		deleteMessage,
		deleteCluster,
		pinnedMessage,
		isPinned,
		togglePinMessage,
		unpinMessage,
		pinnedMessageLabel,
		scrollToPinnedMessage,
		messageActionsOptions,
		otherMessageActionsOptions,
		uploadingFile,
		showEmojiPicker,
		emojiSearchQuery,
		emojiList,
		toggleEmojiPicker,
		insertEmoji,
		openFilePicker,
		removeAttachment,
		formatFileSize,
		attachmentIcon,
		attachmentIconBg,
		attachmentIconColor,
		isImageFile,
		clusterRowWidth,
		downloadFile,
		showFilePreviewDialog,
		previewFile,
		openFilePreview,
		sendMessage,
		sendMessageOnEnter,
		mediaTab,
		mediaSearchQuery,
		mediaSortAscending,
		toggleMediaSort,
		threadLinks,
		openLink,
		openEventLink,
		formatRelativeDay,
		threadFiles,
		fileExtensionLabel,
	}
}
