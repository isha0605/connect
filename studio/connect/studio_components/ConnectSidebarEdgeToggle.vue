<script setup>
// The sidebar's collapse button: a round chevron on the sidebar's right border that shows beside the
// pointer while it is over the border. It is fixed to the page and follows the sidebar's right edge,
// since the sidebar hides anything that sticks out of it.
import { computed, inject, onBeforeUnmount, onMounted, ref } from "vue"
import { sidebarCollapsedKey, sidebarToggleKey } from "frappe-ui"

defineProps({
	// Named in the sidebar's block JSON: Studio's build bundles only the lucide icons it finds there.
	icons: { type: Object, default: () => ({}) },
})

const isCollapsed = inject(sidebarCollapsedKey, computed(() => false))
const toggle = inject(sidebarToggleKey, () => {})

const BUTTON_HALF = 12

const anchor = ref(null)
const edge = ref(0)
// Where the pointer is along the border. Null until it first arrives, so a keyboard user finds the
// button at mid-height.
const pointerY = ref(null)
let sidebar = null
let observer = null

function measure() {
	edge.value = sidebar?.getBoundingClientRect().right || 0
}

function follow(event) {
	pointerY.value = Math.min(Math.max(event.clientY, BUTTON_HALF), window.innerHeight - BUTTON_HALF)
}

onMounted(() => {
	sidebar = anchor.value?.closest('[data-slot="sidebar"]')
	if (!sidebar) return
	measure()
	// Follows the edge while the sidebar's width animates.
	observer = new ResizeObserver(measure)
	observer.observe(sidebar)
	window.addEventListener("resize", measure)
})

onBeforeUnmount(() => {
	observer?.disconnect()
	window.removeEventListener("resize", measure)
})
</script>

<template>
	<span ref="anchor" hidden />
	<div v-if="edge" class="edge" :style="{ left: `${edge - 8}px` }" @pointermove="follow">
		<button
			type="button"
			class="edge-button"
			:style="pointerY === null ? null : { top: `${pointerY - BUTTON_HALF}px` }"
			:aria-label="isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
			:aria-expanded="!isCollapsed"
			@click="toggle"
		>
			<span :class="isCollapsed ? icons.expand : icons.collapse" class="edge-icon" aria-hidden="true" />
		</button>
	</div>
</template>

<style scoped>
.edge {
	bottom: 0;
	position: fixed;
	top: 0;
	width: 16px;
	z-index: 30;
}

.edge-button {
	align-items: center;
	background: var(--surface-base);
	border: 1px solid var(--outline-gray-2);
	border-radius: 999px;
	box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
	color: var(--ink-gray-6);
	cursor: pointer;
	display: flex;
	height: 24px;
	justify-content: center;
	left: -4px;
	opacity: 0;
	padding: 0;
	position: absolute;
	top: calc(50% - 12px);
	transition: opacity 150ms ease;
	width: 24px;
}

.edge:hover .edge-button,
.edge-button:focus-visible {
	opacity: 1;
}

.edge-button:hover {
	color: var(--ink-gray-8);
}

.edge-button:focus-visible {
	outline: 2px solid var(--outline-gray-3);
	outline-offset: 1px;
}

.edge-icon {
	height: 14px;
	width: 14px;
}
</style>
