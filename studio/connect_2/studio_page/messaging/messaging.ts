import { ref, computed, watch, onScopeDispose, nextTick } from "vue"
import { toast, call, useFileUpload, initSocket, setConfig } from "frappe-ui"
import { EMOJI_GROUPS } from "./emojis"

export default function setup(context) {
	// ---- State ----
	const selectedThread = ref("")
	const draftMessage = ref("")
	const draftAttachments = ref([])
	let nextAttachmentId = 1
	const showMembersDialog = ref(false)
	const showMediaDialog = ref(false)
	const showTemplatesDialog = ref(false)
	// ---- Profile settings popup (sidebar avatar) ----
	// Two-pane popup, mirroring Raven's own profile settings — distinct from the pre-existing
	// "Settings" SidebarItem above (which edits the customer's saved Requirement via
	// settingsOpen/settingsCompanyName/etc., Studio Variables predating this .ts file's
	// convention of declaring state here instead — left untouched, just named around).
	// Profile is self-service rename; Users is a read-only roster of the caller's own company
	// (customer or partner side — get_my_team auto-detects which).
	const showProfileSettingsDialog = ref(false)
	const profileSettingsSection = ref("profile")
	const editFullName = ref("")
	const editPhone = ref("")
	const editRole = ref("")
	// snapshot of what's actually saved, taken on open and again after a successful save —
	// the Save button stays disabled (same greyed-out look as the composer's Send button
	// with an empty draft) until one of the fields drifts from this baseline.
	const originalFullName = ref("")
	const originalPhone = ref("")
	const originalRole = ref("")
	const savingProfile = ref(false)
	const uploadingProfileImage = ref(false)
	const mediaTab = ref("Links")
	const showAddMemberDialog = ref(false)
	const newMemberEmail = ref("")
	const newMemberPermission = ref("Write")
	const showAddTeamMemberDialog = ref(false)
	const newTeamMemberEmail = ref("")
	const newTeamMemberRole = ref("")
	const newTeamMemberPassword = ref("")
	const addingTeamMember = ref(false)

	// DMs live in the SAME sidebar/chat pane as company deal threads (see unifiedThreadList) —
	// selectedThreadType tracks which kind selectedThread currently refers to, since the two
	// live in different doctypes/resources (Connect Thread vs Connect DM Thread) under the hood.
	const selectedThreadType = ref("company")

	// ---- Threads ----
	// Company deal threads and DM threads share an identical last-message/unread-count shape
	// (see get_my_threads / get_my_dm_threads on the backend) — merging them into one list and
	// sorting by activity is what puts them in one inbox together, WhatsApp/Raven-style.
	function unifiedThreadList() {
		const company = (context.myThreads.data || []).map((t) => ({ ...t, convType: "company" }))
		const dms = (context.myDMThreads.data || []).map((t) => ({ ...t, convType: "dm" }))
		return [...company, ...dms].sort(
			(a, b) => new Date(b.last_message_at).getTime() - new Date(a.last_message_at).getTime(),
		)
	}

	function currentThread() {
		return (
			unifiedThreadList().find((t) => t.name === selectedThread.value && t.convType === selectedThreadType.value) ||
			{}
		)
	}

	function otherPartyName(thread) {
		if (thread && thread.convType === "dm") {
			return capitalizeName(thread.other_user_full_name) || memberDisplayName(thread.other_user)
		}
		const amPartner = context.myContext.data && context.myContext.data.partner
		return amPartner ? thread.customer : thread.partner
	}

	// Company threads carry the partner's uploaded logo (see get_my_threads' partner_logo) — shown
	// only to the customer side, since a partner viewing their own customer threads has no customer
	// logo to show and falls back to Avatar's label-initial rendering instead.
	function threadAvatarImage(thread) {
		if (!thread) return ""
		if (thread.convType === "dm") return thread.other_user_image || ""
		const amPartner = context.myContext.data && context.myContext.data.partner
		return amPartner ? "" : thread.partner_logo || ""
	}

	// ---- Inbox search ----
	// Filters the unified inbox (see unifiedThreadList) by whatever's typed into the Inbox search
	// box (see thread-search-input in the JSON — a real frappe-ui TextInput bound to this ref via
	// Studio's variable binding, not a raw <input>, so it gets frappe-ui's own focus/border styling
	// for free instead of the browser's default blue outline).
	const threadSearchQuery = ref("")

	// ---- Inbox Active/Inactive tabs ----
	// A DM thread has no `status` field at all (Connect DM Thread doesn't carry one — see
	// get_my_dm_threads), so it's always "active"; only a company thread can be closed
	// (see closeThread / Connect Thread's status: Open|Closed).
	const activeInboxTab = ref("active")

	function isThreadActive(thread) {
		return thread.convType !== "company" || thread.status !== "Closed"
	}

	function activeThreadCount() {
		return unifiedThreadList().filter(isThreadActive).length
	}

	function inactiveThreadCount() {
		return unifiedThreadList().filter((t) => !isThreadActive(t)).length
	}

	function filteredThreadList() {
		const query = threadSearchQuery.value.trim().toLowerCase()
		const threads = unifiedThreadList().filter((t) =>
			activeInboxTab.value === "active" ? isThreadActive(t) : !isThreadActive(t),
		)
		if (!query) return threads
		return threads.filter((thread) => {
			const name = (otherPartyName(thread) || "").toLowerCase()
			const lastMessage = (thread.last_message || "").toLowerCase()
			return name.includes(query) || lastMessage.includes(query)
		})
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

	// WhatsApp/Slack-style "Sender: message" preview — the sender label mirrors how a message's
	// own sender name renders in the chat pane (email local-part, capitalized), so the thread
	// list and the open thread agree on how someone's name is shown.
	function threadListPreview(thread) {
		if (!thread || !thread.last_message) return "No messages yet"
		const me = context.myContext.data && context.myContext.data.user
		const sender = thread.last_message_sender
		let label = sender === me ? "You" : (sender || "").split("@")[0]
		if (label && label !== "You") label = label.charAt(0).toUpperCase() + label.slice(1)
		return (label ? label + ": " : "") + thread.last_message
	}

	function threadCreatedLabel() {
		const t = currentThread()
		if (!t.creation || t.convType === "dm") return ""
		return "Group created on " + formatOrdinalDate(new Date(t.creation))
	}

	function isPanelOpen() {
		return showMembersDialog.value || showMediaDialog.value || showTemplatesDialog.value
	}

	function myMessageTemplates() {
		return context.myTemplates.data || []
	}

	// ---- Template search + create ----
	const templateSearchQuery = ref("")
	const showCreateTemplateForm = ref(false)
	const newTemplateTitle = ref("")
	const newTemplateContent = ref("")
	const creatingTemplate = ref(false)

	function filteredMessageTemplates() {
		const query = templateSearchQuery.value.trim().toLowerCase()
		const templates = myMessageTemplates()
		if (!query) return templates
		return templates.filter(
			(t) => (t.title || "").toLowerCase().includes(query) || (t.content || "").toLowerCase().includes(query),
		)
	}

	function openCreateTemplateForm() {
		showCreateTemplateForm.value = true
		newTemplateTitle.value = ""
		newTemplateContent.value = ""
	}

	function closeCreateTemplateForm() {
		showCreateTemplateForm.value = false
		newTemplateTitle.value = ""
		newTemplateContent.value = ""
	}

	async function saveNewTemplate() {
		const title = newTemplateTitle.value.trim()
		const content = newTemplateContent.value.trim()
		if (!title || !content || creatingTemplate.value) return
		creatingTemplate.value = true
		try {
			await call("connect.api.message_templates.create_message_template", { title, content })
			context.myTemplates.reload()
			closeCreateTemplateForm()
			toast({ title: "Template created", icon: "check", iconClasses: "text-green-600" })
		} catch (e) {
			toast({
				title: "Could not create template",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			creatingTemplate.value = false
		}
	}

	// Accepts either a unified-list item ({name, convType, ...}) or a bare thread name (still
	// supported for the odd caller that only has a company-thread id on hand) — always resolves
	// to a definite convType so every step below knows which doctype/resource it's dealing with.
	function selectThread(item) {
		const name = typeof item === "string" ? item : item.name
		const convType = typeof item === "string" ? "company" : item.convType || "company"
		selectedThread.value = name
		selectedThreadType.value = convType
		showMembersDialog.value = false
		showMediaDialog.value = false
		showTemplatesDialog.value = false
		pinnedMessage.value = null

		if (convType === "dm") {
			const other = typeof item === "object" ? item : null
			// No thread-member roster for a DM — seed memberProfiles by hand from what the
			// inbox list already carries, so sender hover cards resolve a name/photo same as
			// they do for a company thread.
			context.memberProfiles.data = other
				? [{ name: other.other_user, full_name: other.other_user_full_name, user_image: other.other_user_image }]
				: []
			context.dmMessages.filters = { dm_thread: name }
			context.dmMessages.reload()
			loadReactions(name, "dm")
			call("connect.api.dm.mark_dm_thread_read", { thread: name })
				.then(() => context.myDMThreads.reload())
				.catch(() => {})
			fetchPinnedMessage()
			return
		}

		context.messages.filters = { thread: name }
		context.messages.reload()
		loadReactions(name, "company")
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
		fetchPinnedMessage()
	}

	// On phone-width screens the thread list and the open conversation share one pane
	// (master-detail); this is what the header's back button calls to return to the list.
	function goBackToThreadList() {
		selectedThread.value = ""
	}

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

	// Without this, useFileUpload's client-side size check (fileSizeLimitMessage) has no
	// limit to compare against and silently lets oversized files through to the raw upload,
	// which then fails as an opaque network error instead of an upfront, readable message.
	// Studio-rendered pages don't get a window.frappe.boot object (unlike desk), so the
	// limit has to be fetched rather than read off boot data.
	call("frappe.core.api.file.get_max_file_size").then((maxFileSize) => {
		if (maxFileSize) setConfig("maxFileSize", maxFileSize)
	})
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

	// DM inbox/thread updates, mirroring handleNewMessage above.
	function handleNewDMMessage(payload) {
		if (selectedThreadType.value === "dm" && payload.dm_thread === selectedThread.value) {
			context.dmMessages.reload()
		}
		context.myDMThreads.reload()
	}
	socket.on("connect_new_dm_message", handleNewDMMessage)
	onScopeDispose(() => socket.off("connect_new_dm_message", handleNewDMMessage))

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

	// Someone else reacted/un-reacted in a conversation — refetch the chips if it's the open one.
	function handleReactionChanged(payload) {
		if (payload.thread === selectedThread.value && !!payload.is_dm === (selectedThreadType.value === "dm")) {
			context.messageReactions.reload()
		}
	}
	socket.on("connect_message_reaction", handleReactionChanged)
	onScopeDispose(() => socket.off("connect_message_reaction", handleReactionChanged))

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

	// DM counterparts to the three handlers above, mirroring them 1:1.
	function handleDMMessageDeleted(payload) {
		if (selectedThreadType.value === "dm" && payload.dm_thread === selectedThread.value) {
			context.dmMessages.reload()
		}
	}
	socket.on("connect_dm_message_deleted", handleDMMessageDeleted)
	onScopeDispose(() => socket.off("connect_dm_message_deleted", handleDMMessageDeleted))

	function handleDMMessageEdited(payload) {
		if (selectedThreadType.value === "dm" && payload.dm_thread === selectedThread.value) {
			context.dmMessages.reload()
		}
	}
	socket.on("connect_dm_message_edited", handleDMMessageEdited)
	onScopeDispose(() => socket.off("connect_dm_message_edited", handleDMMessageEdited))

	function handleDMThreadPinChanged(payload) {
		if (selectedThreadType.value !== "dm" || payload.thread !== selectedThread.value) return
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
	socket.on("connect_dm_thread_pin_changed", handleDMThreadPinChanged)
	onScopeDispose(() => socket.off("connect_dm_thread_pin_changed", handleDMThreadPinChanged))

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

	// messages/dmMessages are frappe-ui list resources capped at 200 rows (see messaging.json),
	// sorted creation DESC — so `.next()` fetches the *next older* page and appends it to the
	// end of `.data`, which is exactly "load more history" for a DESC-sorted list. Set while a
	// fetch is in flight so a burst of scroll events near the top can't fire it more than once
	// concurrently, and so the data-change watcher below (which normally snaps the pane to the
	// bottom on every new message) knows to stay put instead — otherwise appending older
	// messages would immediately yank the pane away from what the user scrolled up to read.
	let isLoadingOlderMessages = false

	async function loadOlderMessages(container: HTMLElement) {
		if (!selectedThread.value || isLoadingOlderMessages) return
		const list = selectedThreadType.value === "dm" ? context.dmMessages : context.messages
		if (!list || list.list.loading || !list.hasNextPage) return

		isLoadingOlderMessages = true
		const prevScrollHeight = container.scrollHeight
		const prevScrollTop = container.scrollTop
		try {
			await list.next()
			await nextTick()
			// Keep whatever the user was looking at pinned in place — without this, prepending
			// older messages above the viewport would shove their current position down the page.
			container.scrollTop = prevScrollTop + (container.scrollHeight - prevScrollHeight)
		} catch (e) {
			// no history-loading affordance to show an error in — silently leave hasNextPage as
			// is, so the next scroll-to-top attempt just retries
		} finally {
			isLoadingOlderMessages = false
		}
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
		if (container.scrollTop < 200) loadOlderMessages(container)

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
		() => [context.messages.data, context.dmMessages.data],
		() => {
			// A load-older-history fetch also lands here (it's the same .data array), but that
			// one manages the scroll position itself (see loadOlderMessages) — jumping to the
			// bottom here too would undo it the instant the older page arrives.
			if (isLoadingOlderMessages) return
			scrollMessagesToBottom()
		},
	)

	onScopeDispose(() => {
		if (stickyDateHideTimer) clearTimeout(stickyDateHideTimer)
		messagesResizeObserver?.disconnect()
	})

	function closeThread() {
		if (!window.confirm("Close this thread?")) return
		call("connect.api.threads.close_thread", { thread: selectedThread.value })
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
	function amPartner() {
		return !!(context.myContext.data && context.myContext.data.partner)
	}

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

	function activeMemberCount() {
		return activeMembers().length
	}

	// Chat header stats — partnerInfo is fetched on demand (see selectThread) rather than folded
	// into get_my_threads, since that resource backs every row in the sidebar and this is only
	// ever needed for whichever one thread is currently open.
	function responseTimeLabel() {
		const p = context.partnerInfo.data
		if (!p || !p.response_time_hours) return ""
		return "Typically " + p.response_time_hours + "h"
	}

	// No hiring flow exists yet anywhere in the app — just acknowledges the click.
	function hirePartner() {
		toast({ title: "Hire flow coming soon", icon: "check", iconClasses: "text-green-600" })
	}

	// ---- Book a slot ----
	const showBookSlotDialog = ref(false)
	const bookSlotDate = ref("")
	const bookSlotTime = ref("")
	const requestingSlot = ref(false)

	function toDateStr(d) {
		return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0")
	}

	function isWeekday(d) {
		const day = d.getDay()
		return day !== 0 && day !== 6
	}

	// Slots are open for the next 10 weekdays from today — there's no per-partner calendar
	// config yet for a longer/shorter booking horizon, just the daily time template (see
	// connect.api.bookings._partner_slot_template).
	const BOOKING_WINDOW_DAYS = 10

	function bookableDateSet() {
		const dates = new Set()
		const d = new Date()
		d.setHours(0, 0, 0, 0)
		while (dates.size < BOOKING_WINDOW_DAYS) {
			if (isWeekday(d)) dates.add(toDateStr(d))
			d.setDate(d.getDate() + 1)
		}
		return dates
	}

	function isBookableDate(dateStr) {
		return bookableDateSet().has(dateStr)
	}

	function nextBookableDate() {
		const d = new Date()
		d.setHours(0, 0, 0, 0)
		while (!isWeekday(d)) d.setDate(d.getDate() + 1)
		return toDateStr(d)
	}

	function reloadBookingSlots() {
		const t = currentThread()
		if (!t.partner) return
		context.bookingSlots.params = { partner: t.partner, booking_date: bookSlotDate.value }
		context.bookingSlots.reload()
	}

	function openBookSlotDialog() {
		bookSlotDate.value = nextBookableDate()
		bookSlotTime.value = ""
		showBookSlotDialog.value = true
		reloadBookingSlots()
	}

	function closeBookSlotDialog() {
		showBookSlotDialog.value = false
	}

	function selectBookingDate(dateStr) {
		if (!isBookableDate(dateStr)) return
		bookSlotDate.value = dateStr
		bookSlotTime.value = ""
		reloadBookingSlots()
	}

	function calendarMonthLabel() {
		if (!bookSlotDate.value) return ""
		return new Date(bookSlotDate.value + "T00:00:00").toLocaleDateString("en-US", { month: "long", year: "numeric" })
	}

	function selectedBookingDateHeading() {
		if (!bookSlotDate.value) return ""
		return new Date(bookSlotDate.value + "T00:00:00").toLocaleDateString("en-US", {
			weekday: "long",
			month: "long",
			day: "numeric",
		})
	}

	// A 6x7 grid (Sun-Sat) covering the selected date's month, padded with the tail of the
	// previous month and the head of the next — same shape convention Requirement's Apps
	// Repeater uses ({name} objects), just wrapped one level deeper for the week rows.
	function calendarWeeks() {
		if (!bookSlotDate.value) return []
		const anchor = new Date(bookSlotDate.value + "T00:00:00")
		const month = anchor.getMonth()
		const gridStart = new Date(anchor.getFullYear(), month, 1)
		gridStart.setDate(gridStart.getDate() - gridStart.getDay())

		const bookable = bookableDateSet()
		const weeks = []
		const cursor = new Date(gridStart)
		for (let w = 0; w < 6; w++) {
			const days = []
			for (let i = 0; i < 7; i++) {
				const dateStr = toDateStr(cursor)
				days.push({
					dateStr,
					dayNumber: cursor.getDate(),
					inCurrentMonth: cursor.getMonth() === month,
					isBookable: bookable.has(dateStr),
					isSelected: dateStr === bookSlotDate.value,
				})
				cursor.setDate(cursor.getDate() + 1)
			}
			weeks.push({ weekIndex: w, days })
		}
		return weeks
	}

	function bookingSlotList() {
		return context.bookingSlots.data || []
	}

	function selectBookingTime(slot) {
		if (!slot || slot.spots_left <= 0) return
		bookSlotTime.value = slot.time
	}

	function formatSlotTime(slot) {
		if (!slot) return ""
		return new Date("2000-01-01T" + slot.time).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })
	}

	function slotSpotsLabel(slot) {
		if (!slot) return ""
		return slot.spots_left > 0 ? "" : "Full"
	}

	function isSlotSelected(slot) {
		return !!(slot && bookSlotTime.value === slot.time)
	}

	function myTimezoneLabel() {
		const offsetMinutes = -new Date().getTimezoneOffset()
		const sign = offsetMinutes >= 0 ? "+" : "-"
		const abs = Math.abs(offsetMinutes)
		const hours = Math.floor(abs / 60)
		const minutes = abs % 60
		return "GMT" + sign + hours + ":" + String(minutes).padStart(2, "0")
	}

	// Whoever the caller isn't — a customer booking sees the partner's team, and vice versa.
	function meetingAttendees() {
		const wantSide = amPartner() ? "Customer" : "Partner"
		return activeMembers().filter((m) => m.side === wantSide)
	}

	function canRequestSlot() {
		return !!bookSlotTime.value && !requestingSlot.value
	}

	async function requestSlot() {
		if (!canRequestSlot()) return
		requestingSlot.value = true
		try {
			await call("connect.api.bookings.request_slot", {
				thread: selectedThread.value,
				booking_date: bookSlotDate.value,
				booking_time: bookSlotTime.value,
			})
			showBookSlotDialog.value = false
			context.messages.reload()
			toast({ title: "Slot requested", icon: "check", iconClasses: "text-green-600" })
		} catch (e) {
			toast({
				title: "Could not request slot",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			requestingSlot.value = false
		}
	}

	// ---- Booking message card ----
	// A Booking-type message stores its snapshot as a JSON blob in `content` (see
	// connect.api.bookings.request_slot), same convention as Requirement messages.
	function parseBookingContent(item) {
		try {
			return JSON.parse((item && item.content) || "{}") || {}
		} catch (e) {
			return {}
		}
	}

	function bookingCardSubtitle(item) {
		const b = parseBookingContent(item)
		if (!b.date) return ""
		const d = new Date(b.date + "T" + (b.time || "00:00:00"))
		return (
			d.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" }) +
			", " +
			d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })
		)
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
		showTemplatesDialog.value = false
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
		const withMentions = escaped.replace(
			/(^|\s)@([^\s@]+)/g,
			(_match, prefix, name) => prefix + '<span style="font-weight: 600">@' + name + "</span>",
		)
		if (!item || !item.is_edited) return withMentions
		const editedSpan =
			'<span style="float: right; margin-left: 8px; margin-top: 6px; margin-right: -6px; font-size: 9px; ' +
			'line-height: 12px; color: var(--ink-gray-5); white-space: nowrap;">Edited</span>'
		return withMentions + editedSpan
	}

	// ---- Requirement cards ----
	// A Requirement-type message stores its snapshot as a JSON blob in `content` (see
	// connect.api.messages.send_message) rather than free text, so it can render as a structured card
	// instead of a text bubble (see message-requirement-card in the JSON).
	function parseRequirementContent(item) {
		try {
			return JSON.parse((item && item.content) || "{}") || {}
		} catch (e) {
			return {}
		}
	}

	const REQUIREMENT_FIELD_LABELS = [
		["company_name", "Company"],
		["country", "Country"],
		["industry", "Industry"],
		["looking_for", "Looking for"],
		["company_size", "Company size"],
		["current_situation", "Current setup"],
		["timeline", "Timeline"],
		["delivery_preference", "Delivery"],
		["budget", "Budget"],
		["apps", "Apps"],
	]

	function requirementFieldRows(req) {
		return REQUIREMENT_FIELD_LABELS.map(([key, label]) => {
			let value = req[key]
			if (key === "apps") value = Array.isArray(value) ? value.join(", ") : value
			return [label, value]
		}).filter(([, value]) => value)
	}

	// The requirement card renders as two stacked boxes rather than one long one — "who they
	// are" up top, "what they need" below.
	const REQUIREMENT_FIELD_KEYS_PRIMARY = new Set(["company_name", "country", "industry", "company_size"])

	function splitRequirementFieldRows(req) {
		const primary = []
		const secondary = []
		REQUIREMENT_FIELD_LABELS.forEach(([key, label]) => {
			let value = req[key]
			if (key === "apps") value = Array.isArray(value) ? value.join(", ") : value
			if (!value) return
			;(REQUIREMENT_FIELD_KEYS_PRIMARY.has(key) ? primary : secondary).push([label, value])
		})
		return { primary, secondary }
	}

	function requirementPrimaryRows(item) {
		return splitRequirementFieldRows(parseRequirementContent(item)).primary
	}

	function requirementSecondaryRows(item) {
		return splitRequirementFieldRows(parseRequirementContent(item)).secondary
	}

	// preview_title-style header for the card — same fallback order a viewer would look for.
	// Also doubles as the Avatar's label (frappe-ui's Avatar falls back to that label's first
	// letter when there's no image, so this drives both the heading and the avatar initial).
	function requirementCardTitle(item) {
		const req = parseRequirementContent(item)
		return req.company_name || req.looking_for || "Requirement details"
	}

	function requirementSubtitle(item) {
		const req = parseRequirementContent(item)
		const parts = []
		if (req.industry) parts.push(req.industry)
		if (req.company_size) parts.push(req.company_size + " employees")
		if (req.country) parts.push(req.country)
		return parts.join(" · ")
	}

	// Wrapped as {name} objects (rather than bare strings) so the Apps Repeater has a real
	// object field to key each Badge by — same shape convention as every other Repeater in
	// this file (see message-item-repeater's dataKey: "name").
	function requirementAppItems(item) {
		const req = parseRequirementContent(item)
		const apps = Array.isArray(req.apps) ? req.apps : []
		return apps.map((name) => ({ name }))
	}

	// Shared by copy and download so both actions always agree on what "the requirement" reads as.
	function requirementDetailsText(item) {
		const rows = requirementFieldRows(parseRequirementContent(item))
		const lines = [requirementCardTitle(item), ""]
		rows.forEach(([label, value]) => lines.push(label + ": " + value))
		return lines.join("\n")
	}

	async function copyRequirementDetails(item) {
		try {
			await navigator.clipboard.writeText(requirementDetailsText(item))
			toast({ title: "Copied to clipboard", icon: "check", iconClasses: "text-green-600" })
		} catch (e) {
			toast({ title: "Could not copy", text: e.message, icon: "x-circle", iconClasses: "text-red-600" })
		}
	}

	// ---- Minimal client-side .docx (OOXML) writer ----
	// A Requirement message is a one-time snapshot with no backing document to fetch/print
	// (see downloadFile for the file-attachment path, which does have one), so this builds
	// the .docx straight from requirementDetailsText's fields. No new bundle dependency (a
	// Studio page script only gets vue/frappe-ui) — a .docx is just a ZIP of a few XML parts,
	// so this hand-rolls an uncompressed (STORE) ZIP writer rather than pulling in a library.
	const CRC32_TABLE = (() => {
		const table = new Uint32Array(256)
		for (let n = 0; n < 256; n++) {
			let c = n
			for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
			table[n] = c >>> 0
		}
		return table
	})()

	function crc32(bytes) {
		let crc = 0xffffffff
		for (let i = 0; i < bytes.length; i++) crc = CRC32_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8)
		return (crc ^ 0xffffffff) >>> 0
	}

	// entries: [{ name, content }] with content as a plain (UTF-8) string.
	function buildZipBlob(entries, mimeType) {
		const encoder = new TextEncoder()
		const localParts = []
		const centralParts = []
		let offset = 0

		entries.forEach((entry) => {
			const nameBytes = encoder.encode(entry.name)
			const dataBytes = encoder.encode(entry.content)
			const crc = crc32(dataBytes)
			const size = dataBytes.length

			const local = new DataView(new ArrayBuffer(30))
			local.setUint32(0, 0x04034b50, true)
			local.setUint16(4, 20, true) // version needed
			local.setUint16(6, 0, true) // general purpose flag
			local.setUint16(8, 0, true) // compression method: store
			local.setUint16(10, 0, true) // mod time
			local.setUint16(12, 0x21, true) // mod date (1980-01-01, the DOS epoch floor)
			local.setUint32(14, crc, true)
			local.setUint32(18, size, true) // compressed size
			local.setUint32(22, size, true) // uncompressed size
			local.setUint16(26, nameBytes.length, true)
			local.setUint16(28, 0, true) // extra field length
			localParts.push(new Uint8Array(local.buffer), nameBytes, dataBytes)

			const central = new DataView(new ArrayBuffer(46))
			central.setUint32(0, 0x02014b50, true)
			central.setUint16(4, 20, true) // version made by
			central.setUint16(6, 20, true) // version needed
			central.setUint16(8, 0, true)
			central.setUint16(10, 0, true)
			central.setUint16(12, 0, true)
			central.setUint16(14, 0x21, true)
			central.setUint32(16, crc, true)
			central.setUint32(20, size, true)
			central.setUint32(24, size, true)
			central.setUint16(28, nameBytes.length, true)
			central.setUint16(30, 0, true) // extra field length
			central.setUint16(32, 0, true) // comment length
			central.setUint16(34, 0, true) // disk number start
			central.setUint16(36, 0, true) // internal file attrs
			central.setUint32(38, 0, true) // external file attrs
			central.setUint32(42, offset, true) // offset of local header
			centralParts.push(new Uint8Array(central.buffer), nameBytes)

			offset += 30 + nameBytes.length + size
		})

		const centralStart = offset
		const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0)

		const end = new DataView(new ArrayBuffer(22))
		end.setUint32(0, 0x06054b50, true)
		end.setUint16(4, 0, true)
		end.setUint16(6, 0, true)
		end.setUint16(8, entries.length, true)
		end.setUint16(10, entries.length, true)
		end.setUint32(12, centralSize, true)
		end.setUint32(16, centralStart, true)
		end.setUint16(20, 0, true)

		return new Blob([...localParts, ...centralParts, new Uint8Array(end.buffer)], { type: mimeType })
	}

	const XML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" }
	function xmlEscape(value) {
		return String(value).replace(/[&<>"']/g, (ch) => XML_ESCAPES[ch])
	}

	function requirementDocumentXml(item) {
		const rows = requirementFieldRows(parseRequirementContent(item))
		const paragraphs = [
			`<w:p><w:pPr><w:spacing w:after="240"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr>` +
				`<w:t xml:space="preserve">${xmlEscape(requirementCardTitle(item))}</w:t></w:r></w:p>`,
		]
		rows.forEach(([label, value]) => {
			paragraphs.push(
				`<w:p><w:pPr><w:spacing w:after="120"/></w:pPr>` +
					`<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">${xmlEscape(label)}: </w:t></w:r>` +
					`<w:r><w:t xml:space="preserve">${xmlEscape(value)}</w:t></w:r></w:p>`,
			)
		})
		return (
			`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
			`<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>` +
			paragraphs.join("") +
			`<w:sectPr/></w:body></w:document>`
		)
	}

	function requirementDocxBlob(item) {
		return buildZipBlob(
			[
				{
					name: "[Content_Types].xml",
					content:
						`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
						`<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">` +
						`<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>` +
						`<Default Extension="xml" ContentType="application/xml"/>` +
						`<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>` +
						`</Types>`,
				},
				{
					name: "_rels/.rels",
					content:
						`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
						`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
						`<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>` +
						`</Relationships>`,
				},
				{ name: "word/document.xml", content: requirementDocumentXml(item) },
			],
			"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		)
	}

	function downloadRequirementDetails(item, event) {
		if (event) {
			event.preventDefault()
			event.stopPropagation()
		}
		try {
			const req = parseRequirementContent(item)
			const blob = requirementDocxBlob(item)
			const blobUrl = URL.createObjectURL(blob)
			const link = document.createElement("a")
			link.href = blobUrl
			const namePart = (req.company_name || "requirement").replace(/[^a-z0-9]+/gi, "-")
			const datePart = new Date(item.creation).toISOString().slice(0, 10)
			link.download = "Requirement-" + namePart + "-" + datePart + ".docx"
			document.body.appendChild(link)
			link.click()
			link.remove()
			URL.revokeObjectURL(blobUrl)
		} catch (e) {
			toast({ title: "Could not download", text: e.message, icon: "x-circle", iconClasses: "text-red-600" })
		}
	}

	// ---- Requirement draft (Contact Partner composer card) ----
	// Landing on a brand-new thread via "Contact Partner" seeds this instead of auto-sending —
	// same staged-before-send pattern as a file attachment: the customer reviews/edits it in a
	// popup, and it only ever becomes a real message once Send is pressed.
	const draftRequirement = ref(null)
	const showRequirementPreviewDialog = ref(false)
	const editCompanyName = ref("")
	const editCountry = ref("")
	const editIndustry = ref("")
	const editLookingFor = ref("")
	const editCompanySize = ref("")
	const editCurrentSituation = ref("")
	const editTimeline = ref("")
	const editDeliveryPreference = ref("")
	const editBudget = ref("")
	const editAppsText = ref("")

	async function fetchRequirementDraft() {
		try {
			const snapshot = await call("connect.api.threads.get_requirement_snapshot")
			if (snapshot) draftRequirement.value = snapshot
		} catch (e) {
			// no saved requirement to prefill — composer just starts empty, same as before
		}
	}

	function requirementDraftSummary() {
		if (!draftRequirement.value) return ""
		const req = draftRequirement.value
		return [req.industry, req.looking_for].filter(Boolean).join(" · ") || "Tap to review"
	}

	function openRequirementPreview() {
		if (!draftRequirement.value) return
		const req = draftRequirement.value
		editCompanyName.value = req.company_name || ""
		editCountry.value = req.country || ""
		editIndustry.value = req.industry || ""
		editLookingFor.value = req.looking_for || ""
		editCompanySize.value = req.company_size || ""
		editCurrentSituation.value = req.current_situation || ""
		editTimeline.value = req.timeline || ""
		editDeliveryPreference.value = req.delivery_preference || ""
		editBudget.value = req.budget || ""
		editAppsText.value = (req.apps || []).join(", ")
		showRequirementPreviewDialog.value = true
	}

	function closeRequirementPreview() {
		showRequirementPreviewDialog.value = false
	}

	function saveRequirementDraftEdits() {
		draftRequirement.value = {
			company_name: editCompanyName.value.trim(),
			country: editCountry.value.trim(),
			industry: editIndustry.value.trim(),
			looking_for: editLookingFor.value.trim(),
			company_size: editCompanySize.value.trim(),
			current_situation: editCurrentSituation.value.trim(),
			timeline: editTimeline.value.trim(),
			delivery_preference: editDeliveryPreference.value.trim(),
			budget: editBudget.value.trim(),
			apps: editAppsText.value
				.split(",")
				.map((a) => a.trim())
				.filter(Boolean),
		}
		showRequirementPreviewDialog.value = false
	}

	function removeRequirementDraft() {
		draftRequirement.value = null
	}

	// ---- Profile settings popup ----
	function openProfileSettings() {
		profileSettingsSection.value = "profile"
		const profile = context.myProfile.data
		editFullName.value = (profile && profile.full_name) || ""
		editPhone.value = (profile && profile.phone) || ""
		editRole.value = (profile && profile.role) || ""
		originalFullName.value = editFullName.value
		originalPhone.value = editPhone.value
		originalRole.value = editRole.value
		showProfileSettingsDialog.value = true
	}

	function selectProfileSettingsSection(section) {
		profileSettingsSection.value = section
	}

	async function saveMyProfile() {
		const fullName = editFullName.value.trim()
		if (!fullName || savingProfile.value) return
		savingProfile.value = true
		try {
			await call("connect.api.account.update_my_profile", {
				full_name: fullName,
				phone: editPhone.value.trim(),
				role: editRole.value.trim(),
			})
			await context.myProfile.reload()
			originalFullName.value = editFullName.value
			originalPhone.value = editPhone.value
			originalRole.value = editRole.value
			toast({ title: "Profile updated", icon: "check", iconClasses: "text-green-600" })
		} catch (e) {
			toast({
				title: "Could not update profile",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			savingProfile.value = false
		}
	}

	// picking a new avatar happens the same way as chat attachments (see openFilePicker) —
	// a throwaway <input> is the smallest way to reach the browser's native file dialog.
	function openProfileImagePicker() {
		if (uploadingProfileImage.value) return
		const input = document.createElement("input")
		input.type = "file"
		input.accept = "image/*"
		input.style.display = "none"
		input.addEventListener("change", () => {
			const file = input.files && input.files[0]
			if (file) uploadProfileImage(file)
			input.remove()
		})
		document.body.appendChild(input)
		input.click()
	}

	function uploadProfileImage(file) {
		uploadingProfileImage.value = true
		const { upload } = useFileUpload()
		upload(file, { upload_endpoint: "/api/method/connect.api.account.upload_profile_image" })
			.then(() => {
				context.myProfile.reload()
				toast({ title: "Photo updated", icon: "check", iconClasses: "text-green-600" })
			})
			.catch((e) => {
				toast({
					title: "Could not upload photo",
					text: e.messages ? e.messages[0] : e.message,
					icon: "x-circle",
					iconClasses: "text-red-600",
				})
			})
			.finally(() => {
				uploadingProfileImage.value = false
			})
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
		call("connect.api.threads.add_thread_member", {
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

	const showDisableTeamMemberDialog = ref(false)
	const memberToDisable = ref(null)
	const disablingTeamMember = ref(false)

	function confirmDisableTeamMember(item) {
		memberToDisable.value = item
		showDisableTeamMemberDialog.value = true
	}

	async function disableTeamMember() {
		if (!memberToDisable.value || disablingTeamMember.value) return
		disablingTeamMember.value = true
		try {
			await call("connect.api.account.remove_team_member", { member: memberToDisable.value.name })
			showDisableTeamMemberDialog.value = false
			memberToDisable.value = null
			context.myTeam.reload()
			toast({ title: "Team member disabled", icon: "check", iconClasses: "text-green-600" })
		} catch (e) {
			toast({
				title: "Could not disable team member",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			disablingTeamMember.value = false
		}
	}

	function teamRowOptions(item) {
		const me = context.myContext.data && context.myContext.data.user
		const disabled = !isAnyAdmin() || item.user === me
		return [
			{ label: "Disable", icon: "lucide-user-minus", theme: "red", disabled, onClick: () => confirmDisableTeamMember(item) },
		]
	}

	async function addTeamMember() {
		if (!newTeamMemberEmail.value) {
			toast({ title: "Enter an email", icon: "x-circle", iconClasses: "text-red-600" })
			return
		}
		addingTeamMember.value = true
		try {
			const data = await call("connect.api.account.add_team_member", {
				email: newTeamMemberEmail.value,
				role: newTeamMemberRole.value || null,
				password: newTeamMemberPassword.value || null,
			})
			showAddTeamMemberDialog.value = false
			newTeamMemberEmail.value = ""
			newTeamMemberRole.value = ""
			newTeamMemberPassword.value = ""
			context.myTeam.reload()
			toast({
				title: data && data.created_user ? "New account created and added" : "Team member added",
				icon: "check",
				iconClasses: "text-green-600",
			})
		} catch (e) {
			toast({
				title: "Could not add team member",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			addingTeamMember.value = false
		}
	}

	// ---- Messages ----
	const uploadingFile = computed(() => draftAttachments.value.some((a) => a.uploading))

	function messageActionsOptions(item) {
		if (!item || !isMine(item.sender)) return []
		const options = []
		if (!item.isFileCluster) {
			options.push({ label: "Reply", icon: "lucide-reply", onClick: () => startReply(item) })
		}
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
		const onDelete = item.isFileCluster ? () => confirmDeleteCluster(item) : () => confirmDeleteMessage(item)
		options.push({ label: "Delete", icon: "lucide-trash-2", theme: "red", onClick: onDelete })
		return options
	}

	// Right-click menu for someone else's message — Reply + Pin/Unpin, since edit/delete are
	// sender-only (see messageActionsOptions). File clusters aren't pinnable/replyable.
	function otherMessageActionsOptions(item) {
		if (!item || item.isFileCluster) return []
		return [
			{ label: "Reply", icon: "lucide-reply", onClick: () => startReply(item) },
			{
				label: isPinned(item) ? "Unpin" : "Pin",
				icon: isPinned(item) ? "lucide-pin-off" : "lucide-pin",
				onClick: () => togglePinMessage(item),
			},
		]
	}

	// ---- Hover toolbar (Raven-style) ----
	// Name of the message whose "more" menu or emoji picker is open. Both are portaled out of the row, so
	// the row loses :hover the moment the pointer enters them — this keeps the toolbar (and row
	// highlight) shown for that one message until the menu closes.
	const messageMenuOpenFor = ref(null)

	function messageCopyText(item) {
		if (item.message_type === "Requirement") return requirementDetailsText(item)
		if (item.message_type === "Text") return item.content || ""
		return ""
	}

	async function copyMessage(item) {
		try {
			await navigator.clipboard.writeText(messageCopyText(item))
			toast({ title: "Copied to clipboard", icon: "check", iconClasses: "text-green-600" })
		} catch (e) {
			toast({ title: "Could not copy", text: e.message, icon: "x-circle", iconClasses: "text-red-600" })
		}
	}

	// The toolbar's "..." menu: the same four actions for everyone, plus Edit/Delete on your own
	// messages. File clusters can't be replied to, pinned or copied, so they only get Delete (yours).
	function messageMoreOptions(item) {
		if (!item) return []
		const mine = isMine(item.sender)
		if (item.isFileCluster) {
			return mine ? [{ label: "Delete", icon: "lucide-trash-2", theme: "red", onClick: () => confirmDeleteCluster(item) }] : []
		}
		const options = [
			{ label: "Reply", icon: "lucide-reply", onClick: () => startReply(item) },
		]
		if (canForwardMessage(item)) {
			options.push({ label: "Forward", icon: "lucide-forward", onClick: () => openForwardDialog(item) })
		}
		if (messageCopyText(item)) options.push({ label: "Copy", icon: "lucide-copy", onClick: () => copyMessage(item) })
		options.push({
			label: isPinned(item) ? "Unpin" : "Pin",
			icon: isPinned(item) ? "lucide-pin-off" : "lucide-pin",
			onClick: () => togglePinMessage(item),
		})
		if (mine) {
			if (item.message_type === "Text") {
				options.push({ label: "Edit", icon: "lucide-pencil", onClick: () => confirmEditMessage(item) })
			}
			options.push({ label: "Delete", icon: "lucide-trash-2", theme: "red", onClick: () => confirmDeleteMessage(item) })
		}
		return options
	}

	// ---- Reactions ----
	// One call loads every reaction in the open conversation (connect.api.messages.get_reactions) and the
	// chips under each message are grouped from that flat list here. File clusters can't be reacted to.
	// The picker is a Popover holding a search box and a grid of emoji. A message's Popover can't hand the
	// message to the grid's click handlers (they run inside two nested repeaters), so the open picker's
	// message lives here instead.
	const reactionPickerMessage = ref(null)
	const emojiSearchQuery = ref("")

	function setReactionPicker(item, open) {
		reactionPickerMessage.value = open ? item : null
		messageMenuOpenFor.value = open ? item.name : null
		emojiSearchQuery.value = ""
	}

	// The emoji groups still matching the search box; a group with no match drops out.
	function emojiPickerSections() {
		const query = emojiSearchQuery.value.trim().toLowerCase()
		return EMOJI_GROUPS.map((g) => ({
			key: g.group,
			group: g.group,
			emojis: g.options
				.filter((o) => !query || o.label.toLowerCase().includes(query))
				.map((o) => ({ key: o.value, emoji: o.value })),
		})).filter((g) => g.emojis.length)
	}

	function pickReaction(emoji) {
		const item = reactionPickerMessage.value
		if (!item) return
		setReactionPicker(item, false)
		toggleReaction(item, emoji)
	}

	function loadReactions(thread, convType) {
		context.messageReactions.data = []
		context.messageReactions.params = { thread, is_dm: convType === "dm" ? 1 : 0 }
		context.messageReactions.reload()
	}

	// One chip per distinct emoji on a message, in the order the emojis were first used. `item` rides along
	// on each chip because a chip's own click handler only sees the chip, not the message it belongs to.
	function messageReactionGroups(item) {
		const groups = new Map()
		for (const reaction of context.messageReactions.data || []) {
			if (reaction.message !== item.name) continue
			let group = groups.get(reaction.emoji)
			if (!group) {
				group = { key: reaction.emoji, emoji: reaction.emoji, count: 0, mine: false, names: [], item }
				groups.set(reaction.emoji, group)
			}
			group.count += 1
			if (isMine(reaction.user)) {
				group.mine = true
				group.names.unshift("You")
			} else {
				group.names.push(reaction.full_name ? capitalizeName(reaction.full_name) : memberDisplayName(reaction.user))
			}
		}
		return [...groups.values()].map((g) => ({ ...g, tooltip: g.names.join(", ") + " reacted with " + g.emoji }))
	}

	async function toggleReaction(item, emoji) {
		if (!item || item.isFileCluster || !emoji) return
		try {
			await call("connect.api.messages.toggle_reaction", {
				message: item.name,
				is_dm: selectedThreadType.value === "dm" ? 1 : 0,
				emoji,
			})
			context.messageReactions.reload()
		} catch (e) {
			toast({
				title: "Could not add reaction",
				text: permissionAwareErrorText(e, "You can't react in this conversation."),
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		}
	}

	// ---- Forward message ----
	// Which conversations can receive a forward is decided server-side (see
	// connect.api.messages.get_forward_targets: Write access, not closed, not removed). Names and
	// avatars come from the unified inbox list the page already has, so the dialog only needs the
	// eligible names back. Requirement/booking cards and file clusters aren't forwardable.
	const showForwardDialog = ref(false)
	const messageToForward = ref(null)
	const forwardTargets = ref({ company: [], dm: [] })
	const loadingForwardTargets = ref(false)
	const forwardSearchQuery = ref("")
	const forwardTarget = ref(null)
	const forwardingMessage = ref(false)

	function canForwardMessage(item) {
		return !!item && !item.isFileCluster && (item.message_type === "Text" || item.message_type === "File")
	}

	async function openForwardDialog(item) {
		messageToForward.value = item
		forwardSearchQuery.value = ""
		forwardTarget.value = null
		forwardTargets.value = { company: [], dm: [] }
		loadingForwardTargets.value = true
		showForwardDialog.value = true
		try {
			forwardTargets.value = await call("connect.api.messages.get_forward_targets")
		} catch (e) {
			showForwardDialog.value = false
			toast({
				title: "Could not load conversations",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			loadingForwardTargets.value = false
		}
	}

	// The eligible conversations minus the one the message is already in, filtered by the dialog's search box.
	function forwardThreadList() {
		const companyNames = new Set(forwardTargets.value.company)
		const dmNames = new Set(forwardTargets.value.dm)
		const query = forwardSearchQuery.value.trim().toLowerCase()
		return unifiedThreadList()
			.filter((t) => (t.convType === "dm" ? dmNames.has(t.name) : companyNames.has(t.name)))
			.filter((t) => !(t.name === selectedThread.value && t.convType === selectedThreadType.value))
			.filter((t) => !query || (otherPartyName(t) || "").toLowerCase().includes(query))
			.map((t) => ({ ...t, key: t.convType + ":" + t.name }))
	}

	async function forwardMessage() {
		const item = messageToForward.value
		const target = forwardTarget.value
		if (!item || !target || forwardingMessage.value) return
		forwardingMessage.value = true
		try {
			await call("connect.api.messages.forward_message", {
				message: item.name,
				source_is_dm: selectedThreadType.value === "dm" ? 1 : 0,
				target_thread: target.name,
				target_is_dm: target.convType === "dm" ? 1 : 0,
			})
			showForwardDialog.value = false
			messageToForward.value = null
			forwardTarget.value = null
			toast({ title: "Message forwarded", icon: "check", iconClasses: "text-green-600" })
			context.myThreads.reload()
			context.myDMThreads.reload()
		} catch (e) {
			toast({
				title: "Could not forward message",
				text: permissionAwareErrorText(e, "You can't post in that conversation."),
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			forwardingMessage.value = false
		}
	}

	const showDeleteMessageDialog = ref(false)
	const messageToDelete = ref(null)
	const deletingMessage = ref(false)

	function confirmDeleteMessage(item) {
		messageToDelete.value = item
		showDeleteMessageDialog.value = true
	}

	// The backend now enforces edit/delete ownership via Frappe's own permission system
	// (has_message_permission/has_dm_message_permission) instead of a custom app-level check,
	// so a denied attempt surfaces as a generic PermissionError with no specific message —
	// swap in our own wording for that one case rather than showing Frappe's raw text.
	function permissionAwareErrorText(e, deniedText) {
		if (e.exc_type === "PermissionError") return deniedText
		return e.messages ? e.messages[0] : e.message
	}

	async function deleteMessage() {
		if (!messageToDelete.value || deletingMessage.value) return
		deletingMessage.value = true
		try {
			const isDM = selectedThreadType.value === "dm"
			await call(isDM ? "connect.api.dm.delete_dm_message" : "connect.api.messages.delete_message", {
				message: messageToDelete.value.name,
			})
			showDeleteMessageDialog.value = false
			messageToDelete.value = null
			if (isDM) {
				context.dmMessages.reload()
				context.myDMThreads.reload()
			} else {
				context.messages.reload()
			}
		} catch (e) {
			toast({
				title: "Could not delete message",
				text: permissionAwareErrorText(e, "You don't have permission to delete this message"),
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			deletingMessage.value = false
		}
	}

	// ---- Editing a message ----
	// Editing happens in the composer itself (matching Telegram/WhatsApp Web) rather than a
	// popup — messageToEdit gates an "Editing message" strip above the input and repurposes
	// draftMessage as the edit buffer, so Enter/Send both branch into saveEditedMessage instead
	// of sendMessage while it's set. showEditMessageDialog/editMessageContent are kept around
	// (unused) purely because the old Edit dialog's JSON block still references them — leaving
	// it in place but permanently unreachable, rather than excising it, is the same low-risk
	// approach that worked the last time this dialog was retired.
	const showEditMessageDialog = ref(false)
	const messageToEdit = ref(null)
	const editMessageContent = ref("")
	const editingMessage = ref(false)

	function confirmEditMessage(item) {
		if (!item || item.isFileCluster || item.message_type !== "Text" || !isMine(item.sender)) return
		replyToMessage.value = null
		messageToEdit.value = item
		draftMessage.value = item.content
		showTemplatesDialog.value = false
		nextTick(() => {
			const el = document.querySelector('[data-component-id="message-input"]') as HTMLTextAreaElement | null
			el?.focus()
		})
	}

	function cancelEditMessage() {
		messageToEdit.value = null
		draftMessage.value = ""
	}

	// ---- Replying to a message ----
	// Same staged-in-composer pattern as editing: replyToMessage gates a "Replying to X" strip
	// above the input, and is cleared once sendMessage() consumes it — quoting happens by
	// reference (reply_to on the new message), not by copying text into the draft.
	const replyToMessage = ref(null)

	function startReply(item) {
		if (!item || item.isFileCluster) return
		messageToEdit.value = null
		replyToMessage.value = item
		nextTick(() => {
			const el = document.querySelector('[data-component-id="message-input"]') as HTMLTextAreaElement | null
			el?.focus()
		})
	}

	function cancelReply() {
		replyToMessage.value = null
	}

	// Resolves a reply_to id against the currently loaded window of messages (the same 200-message
	// list the thread view renders from) — the replied-to message can scroll out of that window on
	// a very long thread, in which case the quote is skipped rather than firing an extra fetch.
	function getRepliedMessage(replyToName) {
		if (!replyToName) return null
		const list = (context.messages.data || []) as any[]
		return list.find((m) => m.name === replyToName) || null
	}

	// Takes the message being quoted directly (not a reply_to id) — the composer passes
	// replyToMessage itself, the bubble template resolves dataItem.reply_to via
	// getRepliedMessage() first and passes that in.
	function replyPreviewText(message) {
		if (!message) return ""
		if (message.message_type === "File") return message.file_name || "Attachment"
		if (message.message_type === "Requirement") return "Requirement details"
		if (message.message_type === "Booking") return "Booking"
		return message.content || ""
	}

	function closeEditMessageDialog() {
		showEditMessageDialog.value = false
		messageToEdit.value = null
		editMessageContent.value = ""
	}

	async function saveEditedMessage() {
		if (!messageToEdit.value || editingMessage.value) return
		const content = draftMessage.value.trim()
		if (!content) return
		editingMessage.value = true
		try {
			const isDM = selectedThreadType.value === "dm"
			await call(isDM ? "connect.api.dm.edit_dm_message" : "connect.api.messages.edit_message", {
				message: messageToEdit.value.name,
				content,
			})
			messageToEdit.value = null
			draftMessage.value = ""
			if (isDM) context.dmMessages.reload()
			else context.messages.reload()
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

	function saveEditedMessageOnEnter(event) {
		if (event && event.key === "Enter" && !event.shiftKey) {
			event.preventDefault()
			saveEditedMessage()
		}
	}

	// ---- Pinning a message ----
	// One pin at a time per thread (see connect.api.messages.pin_message) — the currently pinned
	// message's own fields are kept here rather than re-derived from context.messages.data
	// since the pinned message can scroll out of the loaded window (200-message limit).
	const pinnedMessage = ref(null)

	async function fetchPinnedMessage() {
		if (!selectedThread.value) {
			pinnedMessage.value = null
			return
		}
		try {
			const method =
				selectedThreadType.value === "dm" ? "connect.api.dm.get_pinned_dm_message" : "connect.api.messages.get_pinned_message"
			pinnedMessage.value = await call(method, { thread: selectedThread.value })
		} catch (e) {
			pinnedMessage.value = null
		}
	}

	function isPinned(item) {
		return !!(pinnedMessage.value && item && pinnedMessage.value.name === item.name)
	}

	async function togglePinMessage(item) {
		if (!item || item.isFileCluster) return
		const isDM = selectedThreadType.value === "dm"
		try {
			if (isPinned(item)) {
				await call(isDM ? "connect.api.dm.unpin_dm_message" : "connect.api.messages.unpin_message", {
					thread: selectedThread.value,
				})
				pinnedMessage.value = null
			} else {
				await call(isDM ? "connect.api.dm.pin_dm_message" : "connect.api.messages.pin_message", { message: item.name })
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
			const isDM = selectedThreadType.value === "dm"
			await call(isDM ? "connect.api.dm.unpin_dm_message" : "connect.api.messages.unpin_message", {
				thread: selectedThread.value,
			})
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
		if (pinnedMessage.value.message_type === "File") {
			body = "📎 " + (pinnedMessage.value.file_name || "Attachment")
		} else if (pinnedMessage.value.message_type === "Requirement") {
			body = "Requirement details"
		}
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
			const isDM = selectedThreadType.value === "dm"
			for (const name of names) {
				await call(isDM ? "connect.api.dm.delete_dm_message" : "connect.api.messages.delete_message", { message: name })
			}
			showDeleteClusterDialog.value = false
			clusterToDelete.value = null
			if (isDM) {
				context.dmMessages.reload()
				context.myDMThreads.reload()
			} else {
				context.messages.reload()
			}
		} catch (e) {
			toast({
				title: "Could not delete files",
				text: permissionAwareErrorText(e, "You don't have permission to delete one or more of these files"),
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		} finally {
			deletingCluster.value = false
		}
	}

	async function sendMessage() {
		if (!selectedThread.value || uploadingFile.value) return
		if (messageToEdit.value) {
			await saveEditedMessage()
			return
		}
		if (selectedThreadType.value === "dm") {
			const dmReadyAttachments = draftAttachments.value.filter((a) => a.file_url)
			const content = draftMessage.value.trim()
			if (!content && !dmReadyAttachments.length) return
			const thread = selectedThread.value
			draftMessage.value = ""
			draftAttachments.value = []
			try {
				if (content) {
					await call("connect.api.dm.send_dm_message", { thread, content })
				}
				for (const a of dmReadyAttachments) {
					await call("connect.api.dm.send_dm_message", {
						thread,
						content: "",
						file_url: a.file_url,
						file_name: a.file_name,
						file_type: a.file_type,
						file_size: a.file_size,
					})
				}
				context.dmMessages.reload()
				context.myDMThreads.reload()
			} catch (e) {
				// A multi-part send (text + attachments) can partially succeed before one part
				// fails — reload so the sender's own view reflects whatever actually went
				// through, rather than looking empty until something else triggers a refresh.
				context.dmMessages.reload()
				context.myDMThreads.reload()
				toast({
					title: "Could not send message",
					text: e.messages ? e.messages[0] : e.message,
					icon: "x-circle",
					iconClasses: "text-red-600",
				})
			}
			return
		}
		const readyAttachments = draftAttachments.value.filter((a) => a.file_url)
		const content = draftMessage.value.trim()
		if (!content && !readyAttachments.length && !draftRequirement.value) return

		const thread = selectedThread.value
		const requirementToSend = draftRequirement.value
		const replyToSend = replyToMessage.value ? replyToMessage.value.name : null
		draftMessage.value = ""
		draftAttachments.value = []
		draftRequirement.value = null
		replyToMessage.value = null

		try {
			if (content) {
				await call("connect.api.messages.send_message", { thread, content, reply_to: replyToSend })
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
			if (requirementToSend) {
				await call("connect.api.messages.send_message", { thread, requirement_data: requirementToSend })
			}
			context.messages.reload()
			context.myThreads.reload()
		} catch (e) {
			// Same reasoning as the DM branch above: reflect whatever partially sent instead
			// of leaving the pane looking empty after a mid-send failure.
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
			upload_endpoint:
				selectedThreadType.value === "dm"
					? "/api/method/connect.api.attachments.upload_dm_attachment"
					: "/api/method/connect.api.attachments.upload_chat_attachment",
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

	// A wrapping flex row with no explicit width has no reliable way to shrink to "the width
	// of its widest wrapped line" across browsers — `fit-content`/`max-content` on a multi-line
	// flex container can resolve against the wrong reference box depending on the ancestor
	// chain, which is what kept leaving a stale gap next to small clusters. Computing the exact
	// pixel width ourselves (mirroring the same greedy left-to-right packing flex-wrap does)
	// sidesteps that ambiguity entirely — image/file card widths below match the fixed sizes
	// used in cluster-image-html's max-width and the file-attachment card's width.
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

	// Shift+Enter falls through to the textarea's own default behavior (insert a newline) —
	// only a bare Enter sends/saves, matching the composer's old single-line TextInput where
	// Enter always sent (there was no newline to insert) and Shift made no difference.
	function sendMessageOnEnter(event) {
		if (!event) return
		if (event.key === "Escape" && messageToEdit.value) {
			event.preventDefault()
			cancelEditMessage()
			return
		}
		if (event.key === "Enter" && !event.shiftKey) {
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

	// The composer grows with the message the same way Slack's does: taller while typing a
	// multi-line message, capped (see message-input's maxHeight) with a scrollbar past that.
	// Textarea has no built-in auto-grow, so height is measured and set by hand on every
	// content change — driven off draftMessage itself (not an `input` listener) so it also
	// catches non-typing changes: loading a message into the composer to edit it, inserting a
	// template/mention, or clearing the draft after send.
	//
	// Selector targets `[data-component-id="message-input"]` directly, not a `textarea`
	// descendant of it: Textarea has no label here, so its LabelingWrapper renders no wrapper
	// element at all (`<slot v-else />`) — the bare `<textarea>` IS the component's single root,
	// and that's what data-component-id ends up on. A descendant selector silently matches
	// nothing, which is why resizing did nothing the first time this was wired up.
	function autoResizeComposer() {
		const el = document.querySelector('[data-component-id="message-input"]') as HTMLTextAreaElement | null
		if (!el) return
		el.style.height = "auto"
		el.style.height = el.scrollHeight + "px"
	}
	watch(draftMessage, () => nextTick(autoResizeComposer))

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

	// messages are grouped into per-day sections (see groupedMessages) so `index` here is local
	// to the current day's group, not the flat position in context.messages.data — the first
	// message of a day is never grouped, everything after that is looked up by its global
	// neighbour (safe, since a non-zero local index guarantees the previous message is the same day).
	// The currently open conversation's flat, chronological message list — Connect Message
	// (company threads) and Connect DM Message (DMs) are different doctypes/resources, so
	// every consumer of "the messages" goes through this instead of reading context.messages
	// directly, the same way currentThread() abstracts over the two thread doctypes.
	// The resources fetch creation DESC (newest-first) so the 200-row cap keeps the most
	// recent messages instead of freezing on the oldest 200 once a thread grows past the
	// limit — reverse here, once, back to the ascending order every other reader expects.
	function currentMessages() {
		const raw = selectedThreadType.value === "dm" ? context.dmMessages.data || [] : context.messages.data || []
		return [...raw].reverse()
	}

	// One pass over the flat list per messages update, rather than a findIndex per rendered
	// item (which made isGrouped O(n) per call, O(n²) for the whole thread). Split into
	// per-day buckets the same way groupedMessages does, since "grouped with the previous
	// message" should never be true across a day boundary — day-1's last message and day-2's
	// first message are never adjacent for this purpose even though currentMessages() is one
	// flat, unbroken chronological list.
	const groupedFlagByName = computed(() => {
		const flags = {}
		let lastDateKey = null
		let prev = null
		for (const item of currentMessages()) {
			const dateKey = new Date(item.creation).toDateString()
			if (dateKey !== lastDateKey) {
				lastDateKey = dateKey
				prev = null
			}
			if (prev && prev.sender === item.sender && prev.message_type !== "System") {
				const gapMs = new Date(item.creation).getTime() - new Date(prev.creation).getTime()
				flags[item.name] = gapMs <= 2 * 60 * 1000
			} else {
				flags[item.name] = false
			}
			prev = item
		}
		return flags
	})

	function isGrouped(item) {
		return !!(item && groupedFlagByName.value[item.name])
	}

	// consecutive files from the same sender, sent within 2 minutes of each other, are merged
	// into one synthetic "cluster" item so they render as a single wrapped row with one time
	// underneath instead of a separate full-width row (with its own time) per file
	function clusterFileMessages(items) {
		const result = []
		for (const item of items) {
			const prev = result[result.length - 1]
			const isFile = item.message_type === "File" && !item.is_forwarded
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

	// ---- Sender hover card ----
	// memberProfiles is fetched once per selectThread() (see there) rather than per-message,
	// covering everyone who's ever been a member of the thread — including removed members, so
	// their older messages can still resolve a name/photo on hover.
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

	function memberImage(email) {
		const profile = memberProfile(email)
		return (profile && profile.user_image) || ""
	}

	// Triggered from the "Connect" button on a sender's hover card — starts (or resumes) a
	// 1:1 with them and selects it into the SAME sidebar/chat pane as every other conversation
	// (no separate inbox or popup — see unifiedThreadList).
	async function connectWithUser(email) {
		if (!email || email === (context.myContext.data && context.myContext.data.user)) return
		try {
			const thread = await call("connect.api.dm.start_dm", { user: email })
			await context.myDMThreads.reload()
			const found = (context.myDMThreads.data || []).find((t) => t.name === thread)
			selectThread(
				found
					? { ...found, convType: "dm" }
					: {
							name: thread,
							convType: "dm",
							other_user: email,
							other_user_full_name: memberDisplayName(email),
							other_user_image: memberImage(email),
						},
			)
		} catch (e) {
			toast({
				title: "Could not start conversation",
				text: e.messages ? e.messages[0] : e.message,
				icon: "x-circle",
				iconClasses: "text-red-600",
			})
		}
	}

	// ---- Command palette (Ctrl/Cmd+K) ----
	// A bare frappe-ui Dialog holding a search box and a list of rows. (frappe-ui's own CommandPalette
	// isn't in Studio's production build list, so it can't be used in a built app.) Contacts are the
	// people on the *other* side the caller has interacted with (a customer finds partners, a partner
	// finds customers) — resolved server-side by connect.api.dm.search_contacts, so the same page works
	// for both — followed by the message-search actions.
	const showCommandPalette = ref(false)
	const commandSearchQuery = ref("")
	const commandContacts = ref([])
	const commandActiveIndex = ref(0)
	let commandSearchTimer = null
	let commandSearchToken = 0

	// Ctrl on Windows/Linux, ⌘ on macOS — the palette accepts either, this is just what the footer shows.
	function shortcutModifier() {
		return /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl"
	}

	// Ctrl/Cmd+K toggles the palette; Ctrl/Cmd+G jumps straight to message search (in everything, seeded
	// with whatever is typed in the palette). Both are claimed from the browser (Ctrl+K is Chrome's
	// "search in address bar", Ctrl+G is "find next").
	function handleCommandPaletteShortcut(event: KeyboardEvent) {
		if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return
		const key = event.key.toLowerCase()
		if (key === "k") {
			event.preventDefault()
			showCommandPalette.value = !showCommandPalette.value
		} else if (key === "g") {
			event.preventDefault()
			const query = showCommandPalette.value ? commandSearchQuery.value : ""
			showCommandPalette.value = false
			openMessageSearch("all", query)
		}
	}
	window.addEventListener("keydown", handleCommandPaletteShortcut)
	onScopeDispose(() => window.removeEventListener("keydown", handleCommandPaletteShortcut))

	watch(showCommandPalette, (open) => {
		if (!open) return
		commandSearchQuery.value = ""
		commandActiveIndex.value = 0
		loadCommandContacts("")
	})

	// Typing re-queries after a pause and puts the highlight back on the first row.
	watch(commandSearchQuery, (query) => {
		commandActiveIndex.value = 0
		clearTimeout(commandSearchTimer)
		commandSearchTimer = setTimeout(() => loadCommandContacts(query), 200)
	})
	onScopeDispose(() => clearTimeout(commandSearchTimer))

	async function loadCommandContacts(query) {
		const token = ++commandSearchToken
		try {
			const rows = await call("connect.api.dm.search_contacts", { query })
			// A slower earlier request must not overwrite the results of a newer keystroke.
			if (token === commandSearchToken) commandContacts.value = rows
		} catch (e) {
			if (token === commandSearchToken) commandContacts.value = []
		}
	}

	// "Search in <this conversation>" / "Search anywhere" rows. `kind` is what selectCommandItem dispatches on.
	function commandSearchActions() {
		const query = commandSearchQuery.value.trim()
		const quoted = query ? " for `" + query + "`" : ""
		const actions = []
		if (selectedThread.value) {
			actions.push({
				name: "search-current",
				kind: "search-current",
				title: "Search in " + (otherPartyName(currentThread()) || "this conversation") + quoted,
			})
		}
		actions.push({ name: "search-all", kind: "search-all", title: "Search anywhere" + quoted })
		return actions
	}

	// One flat list so the arrow keys move through contacts and actions alike; the first row of each
	// group carries its heading.
	function commandRows() {
		const amPartner = context.myContext.data && context.myContext.data.partner
		const groups = []
		if (commandContacts.value.length) {
			groups.push({
				title: amPartner ? "Customers" : "Partners",
				items: commandContacts.value.map((u) => ({
					name: u.name,
					kind: "contact",
					title: u.full_name ? capitalizeName(u.full_name) : memberDisplayName(u.name),
					description: u.name,
					image: u.user_image || "",
				})),
			})
		}
		groups.push({ title: "Search messages", items: commandSearchActions() })

		const rows = []
		for (const group of groups) {
			group.items.forEach((item, i) => {
				rows.push({ ...item, groupTitle: i === 0 ? group.title : "", index: rows.length })
			})
		}
		return rows
	}

	// The two lists the palette renders. Each row keeps its index in the flat commandRows() so the arrow
	// keys highlight across both.
	function commandContactRows() {
		return commandRows().filter((r) => r.kind === "contact")
	}

	function commandActionRows() {
		return commandRows().filter((r) => r.kind !== "contact")
	}

	function commandContactsTitle() {
		return context.myContext.data && context.myContext.data.partner ? "Customers" : "Partners"
	}

	function handleCommandKeydown(event: KeyboardEvent) {
		const rows = commandRows()
		if (event.key === "ArrowDown" || event.key === "ArrowUp") {
			event.preventDefault()
			const step = event.key === "ArrowDown" ? 1 : -1
			commandActiveIndex.value = (commandActiveIndex.value + step + rows.length) % rows.length
			nextTick(() => document.querySelector('[data-command-active="true"]')?.scrollIntoView({ block: "nearest" }))
		} else if (event.key === "Enter") {
			event.preventDefault()
			selectCommandItem(rows[commandActiveIndex.value])
		}
	}

	// Closes the palette, then a contact starts (or resumes) the 1:1 and opens it, and a search action
	// opens the message search dialog with what was typed.
	function selectCommandItem(item) {
		if (!item) return
		const query = commandSearchQuery.value
		showCommandPalette.value = false
		if (item.kind === "contact") connectWithUser(item.name)
		else openMessageSearch(item.kind === "search-current" ? "current" : "all", query)
	}

	// ---- Message search ----
	// Searches text and file names in every conversation the caller can read (or just the open one), via
	// connect.api.messages.search_messages. Results carry a conversation label and open that conversation
	// on click, scrolling to the message when it's in the loaded page of messages.
	const showMessageSearch = ref(false)
	const messageSearchQuery = ref("")
	const messageSearchScope = ref("all")
	const messageSearchResults = ref([])
	const searchingMessages = ref(false)
	// Captured when the dialog opens so "this conversation" keeps meaning the same one even if the
	// selection changes underneath it.
	const messageSearchConversation = ref(null)
	let messageSearchTimer = null
	let messageSearchToken = 0
	const MIN_MESSAGE_SEARCH_LENGTH = 2

	function openMessageSearch(scope, query) {
		const thread = selectedThread.value
			? { name: selectedThread.value, convType: selectedThreadType.value, label: otherPartyName(currentThread()) }
			: null
		messageSearchConversation.value = thread
		messageSearchScope.value = scope === "current" && thread ? "current" : "all"
		messageSearchQuery.value = (query || "").trim()
		messageSearchResults.value = []
		showMessageSearch.value = true
		runMessageSearch()
	}

	function messageSearchScopeLabel() {
		const conversation = messageSearchConversation.value
		return conversation ? "In " + (conversation.label || "this conversation") : ""
	}

	function setMessageSearchScope(scope) {
		messageSearchScope.value = scope
		runMessageSearch()
	}

	// The dialog's search box is bound straight to messageSearchQuery; typing re-runs the search after a pause.
	watch(messageSearchQuery, () => {
		clearTimeout(messageSearchTimer)
		messageSearchTimer = setTimeout(runMessageSearch, 250)
	})
	onScopeDispose(() => clearTimeout(messageSearchTimer))

	// Escapes the message text first and only then wraps matches in <mark>, so user-typed markup can't
	// reach the HTML component (same approach as formatMessageContent).
	function highlightMatch(text, query) {
		const escape = (t) => escapeHtmlAttr(t)
		const needle = (query || "").trim().toLowerCase()
		const source = text || ""
		if (!needle) return escape(source)
		const lower = source.toLowerCase()
		let html = ""
		let from = 0
		for (let at = lower.indexOf(needle); at !== -1; at = lower.indexOf(needle, from)) {
			html += escape(source.slice(from, at)) + '<mark style="background: var(--surface-amber-2); color: inherit; border-radius: 2px;">' + escape(source.slice(at, at + needle.length)) + "</mark>"
			from = at + needle.length
		}
		return html + escape(source.slice(from))
	}

	function messageSearchRows() {
		const query = messageSearchQuery.value
		const threads = unifiedThreadList()
		return messageSearchResults.value.map((r) => {
			const convType = r.is_dm ? "dm" : "company"
			const thread = threads.find((t) => t.name === r.thread && t.convType === convType)
			const body = r.message_type === "File" ? "📎 " + (r.file_name || "Attachment") : r.content
			return {
				...r,
				key: convType + ":" + r.name,
				convType,
				conversation: thread ? otherPartyName(thread) : "",
				senderName: r.sender_full_name ? capitalizeName(r.sender_full_name) : memberDisplayName(r.sender),
				when: new Date(r.creation).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
				snippet: highlightMatch(body, query),
			}
		})
	}

	function messageSearchStatus() {
		if (messageSearchQuery.value.trim().length < MIN_MESSAGE_SEARCH_LENGTH) return "Type at least 2 characters to search."
		if (searchingMessages.value) return "Searching..."
		if (!messageSearchResults.value.length) return "No messages found."
		return ""
	}

	async function runMessageSearch() {
		const query = messageSearchQuery.value.trim()
		const token = ++messageSearchToken
		if (query.length < MIN_MESSAGE_SEARCH_LENGTH) {
			messageSearchResults.value = []
			searchingMessages.value = false
			return
		}
		searchingMessages.value = true
		const params = { query }
		const conversation = messageSearchConversation.value
		if (messageSearchScope.value === "current" && conversation) {
			params.thread = conversation.name
			params.is_dm = conversation.convType === "dm" ? 1 : 0
		}
		try {
			const rows = await call("connect.api.messages.search_messages", params)
			if (token === messageSearchToken) messageSearchResults.value = rows
		} catch (e) {
			if (token === messageSearchToken) messageSearchResults.value = []
		} finally {
			if (token === messageSearchToken) searchingMessages.value = false
		}
	}

	// Opens the result's conversation and, once its messages have rendered, scrolls to the message. Only
	// the loaded page of messages is on screen, so an older hit just opens the conversation.
	async function openMessageSearchResult(row) {
		const thread = unifiedThreadList().find((t) => t.name === row.thread && t.convType === row.convType)
		showMessageSearch.value = false
		if (!thread) return
		if (!(selectedThread.value === thread.name && selectedThreadType.value === thread.convType)) selectThread(thread)
		for (let attempt = 0; attempt < 20; attempt++) {
			await new Promise((resolve) => setTimeout(resolve, 100))
			const el = document.querySelector(`[data-message-id="${row.name}"]`)
			if (el) {
				el.scrollIntoView({ behavior: "smooth", block: "center" })
				return
			}
		}
	}

	// Mirrors the media search box's focus treatment (see media-search-box's CSS) on the
	// composer: the pill is a container wrapping a ghost TextInput, so there's no single
	// element a :focus-within rule could live on — the inner input reports focus up instead.
	const composerFocused = ref(false)

	// ---- Media ----
	const mediaSearchQuery = ref("")
	const mediaViewMode = ref("list")
	const mediaSortAscending = ref(false)

	function toggleMediaSort() {
		mediaSortAscending.value = !mediaSortAscending.value
	}

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

	// Strips sentence punctuation a URL regex has no way to distinguish from part of the URL
	// itself (e.g. "check https://example.com." — the trailing period isn't part of the link).
	// Left untouched otherwise, since a URL can legitimately end in these characters.
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
			.filter(
				(item) =>
					!query || item.url.toLowerCase().includes(query) || item.title.toLowerCase().includes(query),
			)
			.sort((a, b) => {
				const diff = new Date(b.creation).getTime() - new Date(a.creation).getTime()
				return mediaSortAscending.value ? -diff : diff
			})
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

	// Default to the thread named in ?thread=<name> (how "Contact Partner" and the pricing
	// estimate flows land here after start_partner_thread), otherwise fall back to the first
	// (most recently active) conversation — company or DM. Selected by name directly rather
	// than looked up in myThreads.data first: a brand-new thread from Contact Partner can lose
	// this race — its own resource fetch beats myThreads' reload to the client, so requiring
	// it to already be *in* that list here would intermittently fall through to the "most
	// recent" fallback instead (usually landing on the same thread by coincidence, since it
	// IS the newest — but skipping the ?requirement=1 handling that only lives in this branch).
	// selectThread() itself needs nothing but the name; it fetches everything else by thread.
	// Placed here (right before return, not up near its own declaration) deliberately: with
	// immediate:true this can fire selectThread() synchronously during setup()'s own execution,
	// and selectThread touches refs like pinnedMessage that are declared further down the file —
	// calling it any earlier hits their temporal dead zone and throws before setup() ever returns.
	watch(
		() => [context.myThreads?.data, context.myDMThreads?.data],
		() => {
			const list = unifiedThreadList()

			if (!selectedThread.value) {
				const params = new URLSearchParams(window.location.search)
				const requested = params.get("thread")
				if (requested) {
					selectThread(requested)
					// set by start_partner_thread's is_new_thread — a brand-new Contact-Partner thread
					// seeds the composer with a reviewable Requirement draft instead of auto-sending one.
					// Consumed once: stripped from the URL right after, so a later reload of this same
					// link (or revisiting the thread) doesn't keep re-seeding an already-sent draft.
					if (params.get("requirement") === "1") {
						fetchRequirementDraft()
						params.delete("requirement")
						const newSearch = params.toString()
						window.history.replaceState({}, "", window.location.pathname + (newSearch ? "?" + newSearch : ""))
					}
					return
				}
				// On phone-width screens the page opens on the thread list (master-detail), so skip
				// the auto-open-most-recent-conversation default that desktop/tablet relies on.
				if (list.length && window.innerWidth >= 576) selectThread(list[0])
				return
			}

			// Self-heal a ?thread= (or otherwise) selection that doesn't actually exist once both
			// lists have genuinely finished loading — e.g. a Contact-Partner link left in the URL
			// from an earlier visit, pointing at a thread that's since been deleted. Gated on both
			// resources actually being loaded so this never fires against the brief window where a
			// brand-new Contact-Partner thread is selected before myThreads' reload has caught up
			// (see the branch above) — only a thread that's missing after a real load is treated as
			// gone, falling back to the most recent conversation instead of leaving the pane stuck.
			const haveData = Boolean(context.myThreads?.data && context.myDMThreads?.data)
			const stillExists = list.some((t) => t.name === selectedThread.value && t.convType === selectedThreadType.value)
			if (haveData && !stillExists && list.length) selectThread(list[0])
		},
		{ immediate: true },
	)

	return {
		selectedThread,
		draftMessage,
		uploadingFile,
		draftAttachments,
		requirementCardTitle,
		requirementSubtitle,
		requirementAppItems,
		parseRequirementContent,
		requirementFieldRows,
		requirementPrimaryRows,
		requirementSecondaryRows,
		copyRequirementDetails,
		downloadRequirementDetails,
		showProfileSettingsDialog,
		profileSettingsSection,
		editFullName,
		editPhone,
		editRole,
		originalFullName,
		originalPhone,
		originalRole,
		savingProfile,
		uploadingProfileImage,
		openProfileSettings,
		selectProfileSettingsSection,
		saveMyProfile,
		openProfileImagePicker,
		draftRequirement,
		showRequirementPreviewDialog,
		editCompanyName,
		editCountry,
		editIndustry,
		editLookingFor,
		editCompanySize,
		editCurrentSituation,
		editTimeline,
		editDeliveryPreference,
		editBudget,
		editAppsText,
		requirementDraftSummary,
		openRequirementPreview,
		closeRequirementPreview,
		saveRequirementDraftEdits,
		removeRequirementDraft,
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
		composerFocused,
		mediaSearchQuery,
		mediaViewMode,
		mediaSortAscending,
		toggleMediaSort,
		fileExtensionLabel,
		showMembersDialog,
		showMediaDialog,
		showTemplatesDialog,
		myMessageTemplates,
		templateSearchQuery,
		filteredMessageTemplates,
		showCreateTemplateForm,
		newTemplateTitle,
		newTemplateContent,
		creatingTemplate,
		openCreateTemplateForm,
		closeCreateTemplateForm,
		saveNewTemplate,
		mediaTab,
		showAddMemberDialog,
		newMemberEmail,
		newMemberPermission,
		isMentioning,
		filteredMentionMembers,
		insertMention,
		insertTemplate,
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
		goBackToThreadList,
		closeThread,
		amPartner,
		isPartnerAdmin,
		isCustomerAdmin,
		isAnyAdmin,
		isRowAdmin,
		activeMembers,
		activeMemberCount,
		responseTimeLabel,
		hirePartner,
		showBookSlotDialog,
		bookSlotDate,
		bookSlotTime,
		requestingSlot,
		openBookSlotDialog,
		closeBookSlotDialog,
		selectBookingDate,
		calendarMonthLabel,
		selectedBookingDateHeading,
		calendarWeeks,
		bookingSlotList,
		selectBookingTime,
		formatSlotTime,
		slotSpotsLabel,
		isSlotSelected,
		myTimezoneLabel,
		meetingAttendees,
		canRequestSlot,
		requestSlot,
		bookingCardSubtitle,
		addMember,
		makeAdmin,
		removeMember,
		memberRowOptions,
		showDisableTeamMemberDialog,
		memberToDisable,
		disablingTeamMember,
		disableTeamMember,
		teamRowOptions,
		showAddTeamMemberDialog,
		newTeamMemberEmail,
		newTeamMemberRole,
		newTeamMemberPassword,
		addingTeamMember,
		addTeamMember,
		messageActionsOptions,
		otherMessageActionsOptions,
		messageMenuOpenFor,
		reactionPickerMessage,
		emojiSearchQuery,
		setReactionPicker,
		emojiPickerSections,
		pickReaction,
		messageReactionGroups,
		toggleReaction,
		messageMoreOptions,
		showForwardDialog,
		messageToForward,
		loadingForwardTargets,
		forwardSearchQuery,
		forwardTarget,
		forwardingMessage,
		forwardThreadList,
		openForwardDialog,
		forwardMessage,
		showDeleteMessageDialog,
		messageToDelete,
		deletingMessage,
		deleteMessage,
		showEditMessageDialog,
		editMessageContent,
		editingMessage,
		messageToEdit,
		confirmEditMessage,
		cancelEditMessage,
		closeEditMessageDialog,
		saveEditedMessage,
		saveEditedMessageOnEnter,
		replyToMessage,
		startReply,
		cancelReply,
		getRepliedMessage,
		replyPreviewText,
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
		isGrouped,
		groupedMessages,
		formatMessageTime,
		onMessagesScroll,
		isDateStuckAndIdle,
		formatDateDivider,
		formatFullDateTime,
		avatarTheme,
		threadAvatarImage,
		threadSearchQuery,
		activeInboxTab,
		activeThreadCount,
		inactiveThreadCount,
		filteredThreadList,
		memberProfile,
		memberDisplayName,
		memberImage,
		selectedThreadType,
		unifiedThreadList,
		currentMessages,
		connectWithUser,
		showCommandPalette,
		commandSearchQuery,
		commandActiveIndex,
		commandRows,
		commandContactRows,
		commandActionRows,
		commandContactsTitle,
		shortcutModifier,
		handleCommandKeydown,
		selectCommandItem,
		showMessageSearch,
		messageSearchQuery,
		messageSearchScope,
		searchingMessages,
		messageSearchRows,
		messageSearchStatus,
		messageSearchScopeLabel,
		messageSearchConversation,
		openMessageSearch,
		setMessageSearchScope,
		openMessageSearchResult,
		threadLinks,
		threadFiles,
		openLink,
		formatRelativeDay,
	}
}
