<script setup>
// An empty marker a page places after a list: when the visitor scrolls it near the bottom of the
// screen, it calls `load`, so the next rows arrive before the visitor reaches the end.
import { onBeforeUnmount, onMounted, ref, watch } from "vue"

const props = defineProps({
	load: { type: Function, required: true },
	// True while rows are loading or when the list has no more rows.
	disabled: { type: Boolean, default: false },
})

// Starts loading this far before the marker scrolls into view.
const LOAD_AHEAD = "400px"

const marker = ref(null)
const isNearView = ref(false)
let observer = null

function loadIfNeeded() {
	if (isNearView.value && !props.disabled) props.load()
}

onMounted(() => {
	observer = new IntersectionObserver(
		([entry]) => {
			isNearView.value = entry.isIntersecting
			loadIfNeeded()
		},
		{ rootMargin: `0px 0px ${LOAD_AHEAD} 0px` },
	)
	observer.observe(marker.value)
})

// A short page can leave the marker in view after a load: keep loading until it scrolls away.
watch(() => props.disabled, loadIfNeeded)

onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
	<div ref="marker" class="load-more-sentinel" aria-hidden="true" />
</template>

<style scoped>
.load-more-sentinel {
	width: 100%;
	height: 1px;
}
</style>
