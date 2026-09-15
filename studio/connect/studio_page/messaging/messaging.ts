import { ref, computed, watch, onScopeDispose, nextTick, reactive } from "vue"
import { toast } from "frappe-ui"

export default function setup(context) {
	// ==============================================================================================
	// MOCK DATA — this page is intentionally disconnected from the Connect backend (no API Resource
	// calls, no Document List resources, no realtime socket) so the UI can be redesigned freely
	// without touching the live chat in connect-2. Everything below stands in for what the Studio
	// "resources" (now removed from messaging.json) used to fetch. Every binding elsewhere in this
	// page reads from `myThreads.data`, `messages.data`, etc. exactly as before, so
	// filling in real-looking content here is enough to preview real layouts — no JSON changes needed.
	// ==============================================================================================

	// TODO(human): Fill in the mock dataset below to match whatever conversation(s) you want to
	// design against. Field shapes (mirrors the real Connect Message / Connect Thread Member /
	// Partner doctypes and connect.api.threads/account responses):
	//
	// MOCK_MY_CONTEXT — the viewer's own identity. Set exactly one of partner/customer, null the
	// other, to preview that side of the page:
	//   { user: "you@example.com", partner: { is_admin: true } | null, customer: { is_admin: true } | null }
	//
	// MOCK_THREADS — inbox list, newest-first:
	//   { name, customer, partner, partner_logo, last_message, last_message_at, last_message_sender, creation }
	//
	// MOCK_MESSAGES — chat messages, any order (client-sorted by creation):
	//   { name, thread, sender, content, creation, message_type: "Text" | "File",
	//     file_name?, file_type?, file_size?, attachment?, is_edited? }
	//
	// MOCK_THREAD_MEMBERS — roster rows:
	//   { name, thread, user, side: "Partner" | "Customer", is_removed }
	//
	// MOCK_MEMBER_PROFILES — one entry per user email referenced above:
	//   { name /* email */, full_name, user_image }
	//
	// MOCK_PARTNERS — one row per partner referenced in MOCK_THREADS:
	//   { name, logo, response_time_hours }
	//
	// MOCK_SHORTLIST — partner names (strings) the mock customer has shortlisted
	//
	// MOCK_THREAD_ADMINS — per thread name: { partner_admin: <email>, customer_admin: <email> }

	// Pinned to "today" rather than a fixed date so the inbox/message timestamps always render
	// as clock time ("12:16 pm") instead of ageing into a full date string.
	const mockNow = new Date()
	function mockToday(hours, minutes) {
		const d = new Date(mockNow.getTime())
		d.setHours(hours, minutes, 0, 0)
		return d.toISOString()
	}

	const MOCK_MY_CONTEXT = {
		user: "you@bluewaveretail.com",
		partner: null,
		customer: { is_admin: true },
	}

	const MOCK_THREADS = [
		{
			name: "thread-tridots-tech",
			customer: "Bluewave Retail",
			partner: "Tridots Tech",
			partner_logo: "",
			last_message: "Hi Tridots, we're looking at a Starter pack implementation for ERPNext. Could you take this on?",
			last_message_at: mockToday(12, 16),
			last_message_sender: "you@bluewaveretail.com",
			creation: mockToday(12, 16),
		},
	]

	const MOCK_MESSAGES = [
		{
			name: "msg-tridots-1",
			thread: "thread-tridots-tech",
			sender: "you@bluewaveretail.com",
			content: "Hi Tridots, we're looking at a Starter pack implementation for ERPNext. Could you take this on?",
			creation: mockToday(12, 16),
			message_type: "Text",
		},
		{
			name: "msg-tridots-2",
			thread: "thread-tridots-tech",
			sender: "founder@tridotstech.com",
			content: "",
			creation: mockToday(12, 16),
			message_type: "Company",
			company_name: "Acme Technologies",
			industry: "Retail",
			employee_count: "5-10",
		},
		{
			name: "msg-tridots-3",
			thread: "thread-tridots-tech",
			sender: "founder@tridotstech.com",
			content: "",
			creation: mockToday(12, 17),
			message_type: "Event",
			event_title: "Scheduled an introduction call",
			event_datetime: "Thursday, Sep 10, 3:00 pm",
			event_url: "https://meet.google.com/placeholder",
		},
	]

	const MOCK_THREAD_MEMBERS = [
		{ name: "member-1", thread: "thread-tridots-tech", user: "you@bluewaveretail.com", side: "Customer", is_removed: false },
		{ name: "member-2", thread: "thread-tridots-tech", user: "priya@bluewaveretail.com", side: "Customer", is_removed: false },
		{ name: "member-3", thread: "thread-tridots-tech", user: "founder@tridotstech.com", side: "Partner", is_removed: false },
		{ name: "member-4", thread: "thread-tridots-tech", user: "sales@tridotstech.com", side: "Partner", is_removed: false },
		{ name: "member-5", thread: "thread-tridots-tech", user: "support@tridotstech.com", side: "Partner", is_removed: false },
	]

	const MOCK_MEMBER_PROFILES = [
		{ name: "you@bluewaveretail.com", full_name: "Riya Sharma", user_image: "" },
		{ name: "priya@bluewaveretail.com", full_name: "Priya Nair", user_image: "" },
		{ name: "founder@tridotstech.com", full_name: "Rakesh Sharma", user_image: "https://i.pravatar.cc/150?u=rakesh-sharma-tridots" },
		{ name: "sales@tridotstech.com", full_name: "Meera Shah", user_image: "" },
		{ name: "support@tridotstech.com", full_name: "Karan Mehta", user_image: "" },
	]

	const MOCK_PARTNERS = [{ name: "Tridots Tech", logo: "", response_time_hours: 5 }]

	const MOCK_SHORTLIST = []

	const MOCK_THREAD_ADMINS = {
		"thread-tridots-tech": { customer_admin: "you@bluewaveretail.com", partner_admin: "founder@tridotstech.com" },
	}

	// ==============================================================================================
	// End of mock dataset — everything from here down is plumbing, not content.
	// ==============================================================================================

	// The Studio editor recomputes its live template context on every change as a fresh
	// {...resources, ...whatever setup() returned} object — it never keeps whatever this
	// function mutates on the `context` parameter itself. So these have to be returned at the
	// bottom (see the `return` statement) rather than assigned onto `context` here.
	const myContext = reactive({ data: MOCK_MY_CONTEXT, reload: () => {} })
	const myThreads = reactive({ data: MOCK_THREADS, reload: () => {} })
	const messages = reactive({ data: [], reload: () => {} })
	const threadMembers = reactive({ data: [], reload: () => {} })
	const threadAdmins = reactive({ data: {}, reload: () => {} })
	const memberProfiles = reactive({ data: MOCK_MEMBER_PROFILES, reload: () => {} })
	const partnerInfo = reactive({ data: [], reload: () => {} })
	const myShortlist = reactive({ data: MOCK_SHORTLIST, reload: () => {} })

	// Session-only pinned-message state, keyed by thread — the real backend stores one pinned
	// message per thread; here it just lives in memory for as long as the page is open.
	const pinnedByThread = reactive({})
	// Declared up here (not down by the rest of the pinning code below) because selectThread(),
	// invoked synchronously below via the immediate watcher, calls fetchPinnedMessage() before
	// setup() reaches that section — mock threads are available immediately, unlike the real
	// API resource this replaced, which never resolved before setup() finished running.
	const pinnedMessage = ref(null)

	// ---- State ----
	const selectedThread = ref("")
	const draftMessage = ref("")
	const draftAttachments = ref([])
	let nextAttachmentId = 1
	const togglingShortlist = ref(false)
	const showMembersDialog = ref(false)
	const showMediaDialog = ref(false)

	// ---- Threads (inbox list) ----
	function threadList() {
		return myThreads.data || []
	}

	function currentThread() {
		return threadList().find((t) => t.name === selectedThread.value) || {}
	}

	function amPartner() {
		return !!(myContext.data && myContext.data.partner)
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
		const me = myContext.data && myContext.data.user
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

		messages.data = MOCK_MESSAGES.filter((m) => m.thread === name)
		threadMembers.data = MOCK_THREAD_MEMBERS.filter((m) => m.thread === name)
		threadAdmins.data = MOCK_THREAD_ADMINS[name] || {}
		partnerInfo.data = MOCK_PARTNERS.filter((p) => p.name === currentThread().partner)

		showMembersDialog.value = false
		showMediaDialog.value = false
		fetchPinnedMessage()
	}

	// Auto-select the top conversation (myThreads is server-sorted by last activity) as soon as
	// the inbox list loads, so the pane isn't left on "Select a conversation" on first render.
	// Only fires while nothing is selected yet — later reloads (new message, send, etc.) must
	// never yank the user back to the top thread.
	watch(
		() => myThreads.data,
		(threads) => {
			if (!selectedThread.value && threads && threads.length) selectThread(threads[0])
		},
		{ immediate: true },
	)

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
	watch(() => messages.data, scrollMessagesToBottom)
	onScopeDispose(() => messagesResizeObserver?.disconnect())

	// ---- Conversation header stats ----
	function activeMemberCount() {
		return activeMembers().length
	}

	function activeMembers() {
		return (threadMembers.data || []).filter((m) => !m.is_removed)
	}

	function currentPartner() {
		return (partnerInfo.data || [])[0] || null
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

	const myShortlistNames = computed(() => myShortlist.data || [])

	function isShortlisted() {
		return myShortlistNames.value.includes(currentThread().partner)
	}

	function toggleShortlist() {
		const partner = currentThread().partner
		if (!partner || togglingShortlist.value) return
		const list = myShortlist.data
		const idx = list.indexOf(partner)
		if (idx === -1) list.push(partner)
		else list.splice(idx, 1)
	}

	// No hiring flow exists yet — this page is UI-only, so the button just acknowledges the click.
	function hirePartner() {
		toast({ title: "Hire flow coming soon", icon: "check", iconClasses: "text-green-600" })
	}

	function closeConversation() {
		if (!window.confirm("Close this conversation?")) return
		myThreads.data = myThreads.data.filter((t) => t.name !== selectedThread.value)
		selectedThread.value = ""
		if (myThreads.data.length) selectThread(myThreads.data[0])
		toast({ title: "Conversation closed", icon: "check", iconClasses: "text-green-600" })
	}

	// ---- Admin checks (Members panel) ----
	function isPartnerAdmin() {
		return !!(myContext.data && myContext.data.partner && myContext.data.partner.is_admin)
	}

	function isCustomerAdmin() {
		return !!(myContext.data && myContext.data.customer && myContext.data.customer.is_admin)
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
		const email = newMemberEmail.value
		const side = amPartner() ? "Partner" : "Customer"
		if (!memberProfiles.data.some((p) => p.name === email)) {
			memberProfiles.data.push({ name: email, full_name: "", user_image: "" })
		}
		threadMembers.data.push({
			name: "mock-member-" + Date.now(),
			thread: selectedThread.value,
			user: email,
			side,
			is_removed: false,
		})
		showAddMemberDialog.value = false
		newMemberEmail.value = ""
		newMemberPermission.value = "Write"
		toast({ title: "Member added", icon: "check", iconClasses: "text-green-600" })
	}

	function makeAdmin(item) {
		if (!window.confirm(`Make ${item.user} the admin? You will lose admin rights.`)) return
		const sideKey = item.side === "Partner" ? "partner" : "customer"
		const adminField = item.side === "Partner" ? "partner_admin" : "customer_admin"
		if (myContext.data[sideKey]) myContext.data[sideKey].is_admin = false
		threadAdmins.data = { ...threadAdmins.data, [adminField]: item.user }
		toast({ title: "Admin transferred", icon: "check", iconClasses: "text-green-600" })
	}

	function removeMember(item) {
		if (!window.confirm(`Remove ${item.user} from this thread?`)) return
		const member = threadMembers.data.find((m) => m.name === item.name)
		if (member) member.is_removed = true
		toast({ title: "Member removed", icon: "check", iconClasses: "text-green-600" })
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
		const profiles = memberProfiles.data || []
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
		return senderSide({ sender: myContext.data && myContext.data.user })
	}

	function senderSide(item) {
		const sender = item && item.sender
		const member = (threadMembers.data || []).find((m) => m.user === sender)
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

	// ---- Messages ----
	// The messages resource fetches creation DESC (newest-first) so the 200-row cap keeps the
	// most recent messages — reverse here, once, back to the ascending order every reader expects.
	function currentMessages() {
		return [...(messages.data || [])].reverse()
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
		return sender === (myContext.data && myContext.data.user)
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

	function saveEditedMessage() {
		if (!messageToEdit.value || editingMessage.value) return
		const content = draftMessage.value.trim()
		if (!content) return
		const message = messages.data.find((m) => m.name === messageToEdit.value.name)
		if (message) {
			message.content = content
			message.is_edited = true
		}
		messageToEdit.value = null
		draftMessage.value = ""
	}

	// ---- Deleting a message ----
	function deleteMessage(item) {
		if (!item || !window.confirm("Delete this message?")) return
		messages.data = messages.data.filter((m) => m.name !== item.name)
	}

	// ---- Deleting a whole file cluster ----
	// A cluster is a synthetic client-side grouping of several messages sent close together —
	// deleting the group deletes every file message it contains.
	function deleteCluster(item) {
		const files = (item && item.files) || []
		if (!files.length) return
		const label = files.length === 1 ? "this file" : `these ${files.length} files`
		if (!window.confirm(`Delete ${label}?`)) return
		const names = new Set(files.map((f) => f.name))
		messages.data = messages.data.filter((m) => !names.has(m.name))
	}

	// ---- Pinning a message ----
	// One pin at a time per thread, held in pinnedByThread for the life of the page.
	// (pinnedMessage itself is declared up top — see the comment there for why.)

	function fetchPinnedMessage() {
		pinnedMessage.value = (selectedThread.value && pinnedByThread[selectedThread.value]) || null
	}

	function isPinned(item) {
		return !!(pinnedMessage.value && item && pinnedMessage.value.name === item.name)
	}

	function togglePinMessage(item) {
		if (!item || item.isFileCluster) return
		if (isPinned(item)) {
			delete pinnedByThread[selectedThread.value]
			pinnedMessage.value = null
		} else {
			pinnedByThread[selectedThread.value] = {
				name: item.name,
				sender: item.sender,
				message_type: item.message_type,
				content: item.content,
				file_name: item.file_name,
			}
			pinnedMessage.value = pinnedByThread[selectedThread.value]
		}
	}

	function unpinMessage() {
		if (!selectedThread.value || !pinnedMessage.value) return
		delete pinnedByThread[selectedThread.value]
		pinnedMessage.value = null
	}

	function pinnedMessageLabel() {
		if (!pinnedMessage.value) return ""
		const sender = (pinnedMessage.value.sender || "").split("@")[0]
		const body = pinnedMessage.value.message_type === "File" ? "📎 " + (pinnedMessage.value.file_name || "Attachment") : pinnedMessage.value.content
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

	// No backend to upload to — a local object URL stands in for the file so previews, size,
	// and type all render the same way a real uploaded attachment would.
	function uploadFile(file) {
		const id = nextAttachmentId++
		draftAttachments.value.push({
			id,
			file_name: file.name,
			uploading: false,
			file_url: URL.createObjectURL(file),
			file_type: file.type,
			file_size: file.size,
		})
	}

	function removeAttachment(item) {
		draftAttachments.value = draftAttachments.value.filter((a) => a.id !== item.id)
		if (item.file_url) URL.revokeObjectURL(item.file_url)
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

	// Local object URLs (and any plain reachable URL used in mock data) both work with a
	// straight fetch-to-blob download — no backend download route involved.
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

	function sendMessage() {
		if (!selectedThread.value || uploadingFile.value) return
		if (messageToEdit.value) {
			saveEditedMessage()
			return
		}
		const readyAttachments = draftAttachments.value.filter((a) => a.file_url)
		const content = draftMessage.value.trim()
		if (!content && !readyAttachments.length) return

		const thread = selectedThread.value
		const sender = (myContext.data && myContext.data.user) || ""
		draftMessage.value = ""
		draftAttachments.value = []
		const now = new Date().toISOString()

		if (content) {
			messages.data.push({
				name: "mock-msg-" + Date.now(),
				thread,
				sender,
				content,
				creation: now,
				message_type: "Text",
			})
		}
		readyAttachments.forEach((a, i) => {
			messages.data.push({
				name: "mock-msg-" + Date.now() + "-" + i,
				thread,
				sender,
				content: "",
				creation: now,
				message_type: "File",
				attachment: a.file_url,
				file_name: a.file_name,
				file_type: a.file_type,
				file_size: a.file_size,
			})
		})

		const t = myThreads.data.find((t) => t.name === thread)
		if (t) {
			t.last_message = content || (readyAttachments[0] && readyAttachments[0].file_name) || ""
			t.last_message_at = now
			t.last_message_sender = sender
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
		myContext,
		myThreads,
		messages,
		threadMembers,
		threadAdmins,
		memberProfiles,
		partnerInfo,
		myShortlist,
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
