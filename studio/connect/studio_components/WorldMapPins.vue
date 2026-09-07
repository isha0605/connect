<script setup>
// Renders the dot-matrix world map with region-presence pins, and animates
// (grows, darkens, and pulses with a repeating ring) whichever regions are
// currently selected. Coordinates are in the base map SVG's own space
// (viewBox 0 0 119 60) — cx/cy below were snapped to real dots on that map
// (see connect/public/images/worldmap.svg), not eyeballed.

const props = defineProps({
	selectedRegions: {
		type: Array,
		default: () => [],
	},
})

const IMAGE_URL = "/assets/connect/images/worldmap.svg"

const CLUSTERS = {
	India: [
		[86, 25], [86, 24], [85, 25], [87, 25], [86, 26],
	],
	"Asia Pacific": [
		[96, 32], [96, 31], [97, 32], [95, 31], [97, 31],
	],
	"Middle East": [
		[74, 22], [74, 21], [73, 22], [75, 22], [74, 23],
	],
	Europe: [
		[64, 12], [64, 11], [63, 12], [65, 12], [65, 11],
	],
	Africa: [
		[66, 32], [66, 31], [65, 32], [67, 32], [66, 33],
	],
	Americas: [
		[34, 32], [34, 33], [33, 33], [35, 33], [34, 34],
	],
}

function isSelected(region) {
	return (props.selectedRegions || []).includes(region)
}
</script>

<template>
	<svg viewBox="0 0 119 60" class="world-map-pins" preserveAspectRatio="xMidYMid meet">
		<image :href="IMAGE_URL" x="0" y="0" width="119" height="60" />

		<g v-for="(points, region) in CLUSTERS" :key="region">
			<g v-for="([x, y], i) in points" :key="`${region}-${i}`">
				<!-- expanding ping ring — only rendered while this region is selected -->
				<circle
					v-if="isSelected(region)"
					:cx="x"
					:cy="y"
					class="pin-ping"
				/>
				<circle
					:cx="x"
					:cy="y"
					:r="isSelected(region) ? 1.6 : 1.2"
					:class="['pin-dot', { 'pin-dot--selected': isSelected(region) }]"
				/>
			</g>
		</g>
	</svg>
</template>

<style scoped>
.world-map-pins {
	width: 100%;
	height: auto;
	display: block;
}

.pin-dot {
	fill: var(--ink-gray-5, #a6a6a6);
	transition: r 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), fill 0.25s ease;
}

.pin-dot--selected {
	fill: var(--ink-gray-9, #171717);
}

.pin-ping {
	fill: none;
	stroke: var(--ink-gray-9, #171717);
	stroke-width: 0.3;
	opacity: 0;
	transform-origin: center;
	transform-box: fill-box;
	animation: pin-ping 1.6s ease-out infinite;
}

@keyframes pin-ping {
	0% {
		r: 1.6px;
		opacity: 0.6;
	}
	100% {
		r: 5px;
		opacity: 0;
	}
}
</style>
