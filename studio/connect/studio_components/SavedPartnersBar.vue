<script setup>
// The directory's saved partners, in a small bar at the bottom of the list: the first few logos, how
// many are saved, and a way to the saved page. It shows nothing while nothing is saved.
import { computed, getCurrentInstance, watch } from "vue"
import { Button, createResource } from "frappe-ui"

const props = defineProps({
	// Saved partner names: the account's list, or the browser's for a signed-out visitor.
	names: { type: Array, default: () => [] },
	route: { type: String, default: "/saved-partners" },
})

const LOGOS_SHOWN = 3

const router = getCurrentInstance()?.appContext.config.globalProperties.$router
const shownNames = computed(() => props.names.slice(0, LOGOS_SHOWN))
const partners = createResource({ url: "connect.api.partner.list_partners_by_names" })

// Fetched again only when the partners whose logos show change, not on every save elsewhere.
watch(
	() => shownNames.value.join("\n"),
	() => {
		if (shownNames.value.length) partners.submit({ names: JSON.stringify(shownNames.value) })
	},
	{ immediate: true },
)

// A partner that is no longer listed still counts, and shows its first letter.
const logos = computed(() => {
	const byName = Object.fromEntries((partners.data || []).map((partner) => [partner.name, partner]))
	return shownNames.value.map((name) => {
		const partner = byName[name] || {}
		const title = partner.company_name || name
		return { name, title, image: partner.logo_icon || partner.logo || "", initial: title.charAt(0).toUpperCase() }
	})
})
const moreCount = computed(() => props.names.length - shownNames.value.length)
const countLabel = computed(() => (props.names.length === 1 ? "1 partner saved" : `${props.names.length} partners saved`))

function view() {
	if (router) router.push(props.route)
	else window.location.href = `/connect${props.route}`
}
</script>

<template>
	<div v-if="names.length" class="saved-bar-anchor">
		<section class="saved-bar" aria-label="Saved partners">
			<div class="logos" aria-hidden="true">
				<span
					v-for="logo in logos"
					:key="logo.name"
					class="logo"
					:class="{ empty: !logo.image }"
					:style="logo.image ? { backgroundImage: `url('${logo.image}')` } : null"
					:title="logo.title"
				>
					<template v-if="!logo.image">{{ logo.initial }}</template>
				</span>
				<span v-if="moreCount > 0" class="logo more">+{{ moreCount }}</span>
			</div>
			<span class="count">{{ countLabel }}</span>
			<Button variant="subtle" label="View" @click="view" />
		</section>
	</div>
</template>

<style scoped>
/* Floats over the bottom of the list, centred on it; only the bar itself takes clicks. */
.saved-bar-anchor {
	bottom: 24px;
	display: flex;
	justify-content: center;
	left: 0;
	padding: 0 16px;
	pointer-events: none;
	position: absolute;
	right: 0;
	z-index: 20;
}

.saved-bar {
	align-items: center;
	background: var(--surface-base);
	border: 1px solid var(--outline-gray-2);
	border-radius: 14px;
	box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1), 0 1px 3px rgba(0, 0, 0, 0.06);
	display: flex;
	gap: 10px;
	padding: 8px 8px 8px 12px;
	pointer-events: auto;
}

.logos {
	display: flex;
}

.logo {
	align-items: center;
	background-color: var(--surface-white, #ffffff);
	background-position: center;
	background-repeat: no-repeat;
	background-size: contain;
	border: 2px solid var(--surface-base);
	border-radius: 8px;
	box-sizing: border-box;
	color: var(--ink-gray-7);
	display: flex;
	font-size: 11px;
	font-weight: 600;
	height: 30px;
	justify-content: center;
	margin-right: -8px;
	width: 30px;
}

.logo:last-child {
	margin-right: 0;
}

.logo.empty,
.logo.more {
	background-color: var(--surface-gray-2);
}

.count {
	color: var(--ink-gray-8);
	font-size: 14px;
	font-weight: 500;
	margin: 0 6px 0 4px;
	white-space: nowrap;
}
</style>
