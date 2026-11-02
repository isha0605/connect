<script setup>
// The sidebar's Notifications item, which owns the unread count: a red dot on the bell while the
// sidebar is collapsed, the number beside the label while it is open. A notification that
// arrives while a page is open also pops up as a toast. Clicking opens ConnectNotifications.
import { getCurrentInstance, onBeforeUnmount, onMounted, ref } from "vue"
import { Badge, SidebarItem, call, toast } from "frappe-ui"
import { LOG_API, bodyOf, categoryOf, titleOf } from "@app/utils/notificationLogs"

const TOAST_CHECK_LIMIT = 5

const unread = ref(0)
const router = getCurrentInstance()?.appContext.config.globalProperties.$router
// The newest notification already on screen when the page opened, or already toasted.
let newestSeen = ""

// Frappe's socket is always available on window.frappe.realtime in deployed Studio.
// inject("socket") resolves to null there because no parent provides it, so we use
// the global directly instead.
function frappe_realtime() {
	return window.frappe?.realtime || null
}

async function recount() {
	try {
		unread.value = await call("connect.api.account.get_unread_notification_count")
	} catch {
		unread.value = 0
	}
}

async function newestLogs(limit) {
	const data = await call(`${LOG_API}.get_notification_logs`, { limit })
	return { logs: data.notification_logs || [], users: data.user_info || {} }
}

async function rememberNewest() {
	const { logs } = await newestLogs(1)
	newestSeen = logs[0]?.creation || ""
}

// Frappe sends "notification" to the user each time a Notification Log is made for them.
async function onNotification() {
	recount()
	const { logs, users } = await newestLogs(TOAST_CHECK_LIMIT)
	const arrived = logs.filter((log) => log.creation > newestSeen && !log.read && categoryOf(log))
	if (logs[0] && logs[0].creation > newestSeen) newestSeen = logs[0].creation
	for (const log of arrived.reverse().filter(isWorthAToast)) {
		toast.success(titleOf(log, users), { description: bodyOf(log) })
	}
}

// A new message already shows in Messages; a toast there would say it twice.
function isWorthAToast(log) {
	const onMessages = router?.currentRoute.value.path.startsWith("/messaging")
	return !(onMessages && categoryOf(log) === "messages")
}

function openPanel() {
	window.dispatchEvent(new CustomEvent("connect:open-notifications"))
}

onMounted(() => {
	recount()
	rememberNewest().catch(() => {})
	frappe_realtime()?.on("notification", onNotification)
	window.addEventListener("connect:notifications-read", recount)
})
onBeforeUnmount(() => {
	frappe_realtime()?.off("notification", onNotification)
	window.removeEventListener("connect:notifications-read", recount)
})
</script>

<template>
	<SidebarItem
		label="Notifications"
		:active="false"
		:aria-label="unread ? `Notifications, ${unread} unread` : 'Notifications'"
		@click="openPanel"
	>
		<template #prefix>
			<span class="relative grid place-items-center">
				<span class="lucide-bell size-4 text-ink-gray-6" aria-hidden="true" />
				<span v-if="unread" class="connect-notifications-unread-dot absolute -right-0.5 -top-0.5 size-1.5 rounded-full bg-surface-red-6" />
			</span>
		</template>
		<template #suffix>
			<Badge v-if="unread" class="mr-2" theme="red" variant="subtle" :label="unread > 99 ? '99+' : String(unread)" />
		</template>
	</SidebarItem>
</template>

<style>
/* The count beside the label says it while the sidebar is open; the dot is for collapsed. Not
   scoped: it reads frappe-ui Sidebar's own data-state, outside this component. */
[data-slot="sidebar"][data-state="expanded"] .connect-notifications-unread-dot {
	display: none;
}
</style>
