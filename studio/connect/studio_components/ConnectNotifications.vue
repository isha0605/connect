<script setup>
// Notifications panel for every page with the shared sidebar, laid out like Frappe Central's. The
// sidebar's Notifications item opens it with a "connect:open-notifications" window event. Rows are the
// user's Notification Log entries, read through the framework's own notification APIs.
import { computed, getCurrentInstance, onBeforeUnmount, onMounted, ref } from "vue"
import { Button, Select, Spinner, TabButtons, call, toast } from "frappe-ui"

const LOG_API = "frappe.desk.doctype.notification_log.notification_log"

// Icons match the sidebar items with the same name.
const CATEGORIES = {
	messages: { label: "Messages", icon: "lucide-inbox", tile: "bg-surface-blue-2 text-ink-blue-6" },
	projects: { label: "Projects", icon: "lucide-briefcase", tile: "bg-surface-green-2 text-ink-green-6" },
}

// Mirrors CONNECT_NOTIFICATION_DOCTYPES in connect/notifications.py. Anything else (Frappe's
// impersonation or mail-server alerts) isn't shown.
const CATEGORY_OF_DOCTYPE = {
	"Connect Thread": "messages",
	"Connect DM Thread": "messages",
	"Customer Project": "projects",
	"Project Quote": "projects",
	"Starter Pack Order": "projects",
}

const open = ref(false)
const loading = ref(false)
const logs = ref([])
const users = ref({})
const view = ref("all")
const category = ref("")
const left = ref(0)
const anchor = ref(null)
let refreshBadge = null
const router = getCurrentInstance()?.appContext.config.globalProperties.$router

// Grouped by the linked document, not the subject text, so wording changes never move a row.
function categoryOf(log) {
	return CATEGORY_OF_DOCTYPE[log.document_type] || null
}

function lookOf(log) {
	return CATEGORIES[categoryOf(log)]
}

function senderName(log) {
	return users.value[log.from_user]?.fullname || log.from_user || "Someone"
}

function titleOf(log) {
	if (categoryOf(log) === "messages") return `New message from ${senderName(log)}`
	return plainText(log.subject)
}

function bodyOf(log) {
	if (categoryOf(log) === "messages") return plainText(log.subject)
	return plainText(log.email_content)
}

function plainText(html) {
	const element = document.createElement("div")
	element.innerHTML = html || ""
	return (element.textContent || "").trim()
}

const rows = computed(() =>
	logs.value.filter(
		(log) => (view.value === "all" || !log.read) && (!category.value || categoryOf(log) === category.value),
	),
)

const hasUnread = computed(() => logs.value.some((log) => !log.read))

// "" is "All categories"; Select accepts an empty value as a reset row.
const categoryOptions = [
	{ label: "All categories", value: "", icon: "lucide-list" },
	...Object.entries(CATEGORIES).map(([key, item]) => ({ label: item.label, value: key, icon: item.icon })),
]

async function load() {
	loading.value = true
	try {
		const data = await call(`${LOG_API}.get_notification_logs`, { limit: 50 })
		logs.value = (data.notification_logs || []).filter(categoryOf)
		users.value = data.user_info || {}
	} catch (e) {
		toast.error("Could not load notifications")
	} finally {
		loading.value = false
	}
}

async function markAllRead() {
	logs.value.forEach((log) => (log.read = 1))
	try {
		await call(`${LOG_API}.mark_all_as_read`)
		updateBadge()
	} catch (e) {
		toast.error("Could not mark notifications as read")
		load()
	}
}

function openLog(log) {
	if (!log.read) {
		log.read = 1
		call(`${LOG_API}.mark_as_read`, { docname: log.name })
			.then(updateBadge)
			.catch(() => {})
	}

	const target = linkOf(log)
	if (target && router) {
		close()
		goTo(target)
	}
}

function goTo(target) {
	const destination = router.resolve(target)
	if (destination.path !== router.currentRoute.value.path) {
		router.push(target)
		return
	}

	// Same page: Messaging keeps its URL in sync itself (bypassing the router), so change the address
	// the same way and let it react as it does to Back/Forward.
	window.history.pushState(window.history.state, "", destination.href)
	window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state }))
}

function linkOf(log) {
	// Project notifications store their page (connect.customer…project_notifications.project_link).
	if (log.link) return log.link
	if (log.document_type === "Connect Thread") return { path: "/messaging", query: { thread: log.document_name } }
	if (log.document_type === "Connect DM Thread")
		return { path: "/messaging", query: { thread: log.document_name, type: "dm" } }
	return null
}

function timeAgo(value) {
	const seconds = Math.max(0, (Date.now() - new Date(value.replace(" ", "T")).getTime()) / 1000)
	const steps = [
		[60, "a few seconds ago", null],
		[3600, "a minute ago", 60, "minutes"],
		[86400, "an hour ago", 3600, "hours"],
		[2592000, "a day ago", 86400, "days"],
		[31536000, "a month ago", 2592000, "months"],
	]
	for (const [limit, single, unit, plural] of steps) {
		if (seconds >= limit) continue
		const count = unit ? Math.floor(seconds / unit) : 0
		return count > 1 ? `${count} ${plural} ago` : single
	}
	const years = Math.floor(seconds / 31536000)
	return years > 1 ? `${years} years ago` : "a year ago"
}

// The sidebar's unread count comes from each page's own myContext resource, so the sidebar hands
// over a callback that reloads it.
function updateBadge() {
	try {
		refreshBadge?.()
	} catch (e) {
		// A page without myContext has no badge to refresh.
	}
}

function openPanel(event) {
	refreshBadge = event?.detail?.refreshBadge || null
	// The panel docks to the sidebar's right edge, which moves when the sidebar is expanded.
	left.value = anchor.value?.parentElement?.getBoundingClientRect().right || 0
	open.value = true
	load()
}

function close() {
	open.value = false
}

function onKeydown(event) {
	if (event.key === "Escape" && open.value) close()
}

onMounted(() => {
	window.addEventListener("connect:open-notifications", openPanel)
	window.addEventListener("keydown", onKeydown)
})
onBeforeUnmount(() => {
	window.removeEventListener("connect:open-notifications", openPanel)
	window.removeEventListener("keydown", onKeydown)
})
</script>

<template>
	<span ref="anchor" class="hidden" />
	<Teleport to="body">
		<template v-if="open">
			<div class="fixed inset-0 z-40" @click="close" />
			<aside
				class="fixed bottom-0 top-0 z-50 flex w-[430px] max-w-[calc(100vw-48px)] flex-col border-r border-outline-gray-2 bg-surface-base shadow-xl"
				:style="{ left: `${left}px` }"
				aria-label="Notifications"
			>
				<header class="flex h-11 shrink-0 items-center justify-between border-b border-outline-gray-1 pl-4 pr-3">
					<h2 class="text-lg font-semibold text-ink-gray-9">Notifications</h2>
					<div class="flex items-center gap-1">
						<Button
							variant="ghost"
							icon="lucide-check-check"
							aria-label="Mark all as read"
							:disabled="!hasUnread"
							@click="markAllRead"
						/>
						<Button variant="ghost" icon="lucide-x" aria-label="Close" @click="close" />
					</div>
				</header>

				<div class="flex shrink-0 items-center justify-between px-4 py-3">
					<TabButtons
						v-model="view"
						:options="[
							{ label: 'All', value: 'all' },
							{ label: 'Unread', value: 'unread' },
						]"
					/>
					<Select
						v-model="category"
						:options="categoryOptions"
						aria-label="Category"
					/>
				</div>

				<!-- Same thin scrollbar as the rest of Connect's scrolling lists. -->
				<div
					class="min-h-0 flex-1 overflow-y-auto"
					style="scrollbar-width: thin; scrollbar-color: var(--outline-gray-3) transparent"
				>
					<div v-if="loading && !logs.length" class="flex justify-center py-10">
						<Spinner class="size-5 text-ink-gray-5" />
					</div>

					<div v-else-if="!rows.length" class="flex flex-col items-center gap-2 px-6 py-16 text-center">
						<span class="lucide-bell-off size-6 text-ink-gray-4" />
						<p class="text-base font-medium text-ink-gray-8">
							{{ view === "unread" ? "You're all caught up" : "No notifications yet" }}
						</p>
						<p class="text-p-sm text-ink-gray-5">New messages and updates will show up here.</p>
					</div>

					<button
						v-for="log in rows"
						v-else
						:key="log.name"
						type="button"
						class="flex w-full gap-4 border-b border-outline-gray-1 px-4 py-4 text-left outline-none transition-colors hover:bg-surface-gray-1 focus-visible:bg-surface-gray-2"
						@click="openLog(log)"
					>
						<span
							class="relative grid size-8 shrink-0 place-items-center rounded-2"
							:class="lookOf(log).tile"
						>
							<span :class="lookOf(log).icon" class="size-4" />
							<span
								v-if="!log.read"
								class="absolute -right-0.5 -top-0.5 size-1.5 rounded-full bg-surface-blue-7"
								aria-label="Unread"
							/>
						</span>
						<span class="flex min-w-0 flex-1 flex-col gap-1">
							<span class="flex min-w-0 items-baseline justify-between gap-3">
								<span class="min-w-0 truncate text-sm font-medium text-ink-gray-8">{{ titleOf(log) }}</span>
								<span class="shrink-0 text-sm text-ink-gray-4 md:text-2xs">{{ timeAgo(log.creation) }}</span>
							</span>
							<!-- Same look as the Messages thread list preview: bolder while unread. -->
							<span
								v-if="bodyOf(log)"
								class="min-w-0 truncate text-xs"
								:class="log.read ? 'font-normal text-ink-gray-5' : 'font-medium text-ink-gray-8'"
							>
								{{ bodyOf(log) }}
							</span>
						</span>
					</button>
				</div>
			</aside>
		</template>
	</Teleport>
</template>
