<script setup>
// The person signed in, at the foot of the sidebar, with their theme and Log out.
import { computed, inject } from "vue"
import { Avatar, Dropdown, call, sidebarCollapsedKey, useColorScheme } from "frappe-ui"

const props = defineProps({
	// connect.api.account.get_my_context
	context: { type: Object, default: null },
	// Menu icons, by item, named in the sidebar's block JSON: Studio's build bundles only the lucide
	// icons it finds there, not those in a component's script.
	icons: { type: Object, default: () => ({}) },
})

const THEMES = [
	{ value: "light", label: "Light" },
	{ value: "dark", label: "Dark" },
	{ value: "system", label: "System" },
]

const isCollapsed = inject(sidebarCollapsedKey, computed(() => false))
const { colorScheme, setColorScheme } = useColorScheme()
const name = computed(() => props.context?.full_name || props.context?.user || "")

const menuItems = computed(() => [
	{
		label: "Theme",
		icon: props.icons.theme,
		submenu: THEMES.map((theme) => ({
			label: theme.label,
			icon: props.icons[theme.value],
			selected: colorScheme.value === theme.value,
			onClick: () => setColorScheme(theme.value),
		})),
	},
	{ label: "Log out", icon: props.icons.logOut, onClick: logOut },
])

function logOut() {
	call("logout").then(() => (window.location.href = "/connect/partner-directory-redesign"))
}
</script>

<template>
	<div class="px-2 pb-2">
		<Dropdown :options="menuItems" side="top" align="start">
			<button
				type="button"
				class="flex h-9 w-full items-center gap-2 rounded px-1 text-left hover:bg-surface-gray-3"
				:aria-label="`Account menu for ${name}`"
			>
				<Avatar :label="name" size="sm" />
				<template v-if="!isCollapsed">
					<span class="flex-1 truncate text-base text-ink-gray-8">{{ name }}</span>
					<span class="lucide-chevrons-up-down size-4 shrink-0 text-ink-gray-5" aria-hidden="true" />
				</template>
			</button>
		</Dropdown>
	</div>
</template>
