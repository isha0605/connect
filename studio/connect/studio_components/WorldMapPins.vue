<script setup>
// Renders the dot-matrix world map and highlights regions by re-colouring the
// map's OWN dots. Every coordinate in REGION_DOTS is copied verbatim out of
// connect/public/images/worldmap.svg, so each highlight circle lands exactly
// on top of a base map dot, at the base map's own radius (DOT_R = 0.22 in the
// map's 119x60 viewBox space, on a 1.0 grid pitch).
//
// This replaces the earlier approach of overlaying r=0.78/1.04 circles: those
// were 3.5-4.7x the map's dot size and spilled across neighbouring grid cells,
// so they read as blobs pasted on top of the map rather than as part of it.
//
// Each region's pool is the region's real map dots ordered outward from the
// region centre, so a lit patch grows from the core rather than appearing in a
// corner. How many dots a region lights is driven solely by regionCounts (real
// partner counts from connect.api.partner.region_presence_counts): the region
// with the most partners lights its whole pool, the rest scale down
// proportionally.
//
// Selecting a region does NOT change how many dots are drawn — it only restyles
// the dots already on screen (darker + slightly bolder). Adding dots on select
// would misreport presence, and it reads as the map growing rather than
// highlighting. It is a plain state change, not a looping animation.

const props = defineProps({
	selectedRegions: {
		type: Array,
		default: () => [],
	},
	// { india, asia, middle_east, africa, europe, americas } -> count
	regionCounts: {
		type: Object,
		default: null,
	},
})

const IMAGE_URL = "/assets/connect/images/worldmap.svg"

// The base map's own dots are r=0.22, but they arrive rasterized (the map is an
// <image>), so a vector circle at exactly 0.22 leaves the raster's antialiased
// edge peeking out as a grey crescent. 0.26 covers it while still reading as one
// of the map's dots. Selected dots get a little more weight — both stay far
// inside the 1.0 grid pitch, so dots never bleed into their neighbours.
const DOT_R = 0.26
const SELECTED_R = 0.34
// a region with any presence at all lights at least this many dots, so small
// counts stay legible now that each dot is map-sized
const MIN_DOTS = 6

const REGION_DOTS = {
	India: [
		[86,26], [86,25], [85,26], [87,26], [86,27], [85,25], [86.95,25.03], [85.05,26.92],
		[86.95,26.92], [86,24], [84,26], [88,26], [86.08,27.96], [85,24], [87,24], [84,25],
		[88,25], [84.01,26.92], [88,27], [85.05,27.96], [87,28], [84,24], [88,24], [88,28],
		[86,23], [83,26], [89,26], [86,29], [85,23], [87,23], [83,25], [89,25],
		[89,27], [87,29], [84,23], [88,23], [83,24], [89,24], [89,28], [88,29],
		[86,22], [82,26], [90.01,26], [86.08,29.85], [85,22], [87,22], [82,25], [90.01,25],
		[90.01,27], [86.95,30.03], [83,23], [89,23], [89,29], [84,22], [88,22], [82,24],
		[90.01,24], [90.05,27.96], [87.98,30.03], [86,21],
	],
	Asia: [
		[99,28], [98,28], [100,28], [99,27], [97,29], [98,27], [100,27], [97,28],
		[97,30], [98,31], [97,27], [101,27], [97,31], [99,26], [96,29], [98,26],
		[100,26], [96,28], [96,30], [98,32], [97,26], [101,26], [96,27], [96,31],
		[97,32], [99,25], [95,29], [98,25], [100,25], [95,28], [95,30], [96,26],
		[102,26], [96,32], [97,25], [101,25], [95,27], [95,31], [99,24], [96,25],
		[102,25], [95,26], [94,29], [103,32], [98,24], [100,24], [94,28], [94,30],
		[97,24], [101,24], [94.02,27.09], [101,34], [95,25], [96,24], [102,24], [94,26],
		[104,32], [99,23], [93,29], [98,23],
	],
	"Middle East": [
		[76,22], [76,21], [75,22], [77,22], [76,23], [75,21], [75,23], [77,23],
		[76,20], [74,22], [76,24], [75,20], [74,21], [74,23], [78,23], [75,24],
		[77,24], [74,24], [78,24], [76,19], [73,22], [79,22], [76,25], [75,19],
		[73,21], [79,21], [73,23], [79,23], [75,25], [77,25], [74,19], [78,19],
		[79,20], [73,24], [79,24], [74,25], [78,25], [76,18], [72,22], [80,22],
		[76,26], [75,18], [72,21], [80,21], [80,23], [75,26], [79,19], [73,25],
		[79,25], [74,18], [72,20], [80,20], [80,24], [74,26], [76,17], [73,18],
		[79,18], [80,19], [71,22], [81,22],
	],
	Africa: [
		[67,33], [67,32], [66,33], [68,33], [67,34], [66,32], [68,32], [66,34],
		[68,34], [67,31], [65,33], [69,33], [67,35], [66,31], [68,31], [65,32],
		[69,32], [65,34], [69,34], [66,35], [68,35], [65,31], [69,31], [65,35],
		[69,35], [67,30], [64,33], [70,33], [67,36], [66,30], [68,30], [64,32],
		[70,32], [64,34], [70,34], [66,36], [68,36], [65,30], [69,30], [64,31],
		[70,31], [64,35], [70,35], [65,36], [69,36], [67,29], [63,33], [71,33],
		[67,37], [66,29], [68,29], [63.01,32], [71,32], [63.01,34], [71,34], [66,37],
		[68,37], [64,30], [70,30], [64,36],
	],
	Europe: [
		[65,12], [67,12], [66,13], [65,11], [67,13], [64,12], [68,12], [66,14],
		[65,10], [64,11], [68,13], [65,14], [67,14], [64,10], [68,10], [64,14],
		[68,14], [63.01,12], [69,12], [66,15], [65,9], [69,11], [63.01,13], [69,13],
		[65,15], [67,15], [64,9], [68,9], [63.01,10], [69,10], [63.01,14], [69,14],
		[64,15], [68,15], [70,12], [66,16], [65,8], [70,11], [70,13], [65,16],
		[67,16], [63.01,9], [69,9], [63,15], [69,15], [64,8], [68,8], [62.01,10],
		[70,10], [62.01,14], [70,14], [64,16], [68,16], [66,7], [63.01,8], [69,8],
		[62.01,9], [70,9], [71,12], [62.01,15],
	],
	Americas: [
		[34,35], [34,34], [33.01,35], [35,35], [34,36], [33.01,34], [35,34], [33.01,36],
		[35,36], [34,33], [36,35], [34,37], [33.01,33], [35,33], [36,34], [32.01,36],
		[36,36], [33.01,37], [35,37], [32.01,33], [36,33], [32,37], [36,37], [34,32],
		[37,35], [34,38], [37,34], [37,36], [33.01,38], [35,38], [31,33], [37,33],
		[31,37], [37,37], [32.01,38], [36,38], [38,35], [34,39], [38,34], [38,36],
		[33.01,39], [35,39], [31,38], [37,38], [30,33], [38,37], [32.01,39], [36,39],
		[39,35], [38,38], [37,39], [34,40], [39,34], [39,36], [33.01,40], [35,40],
		[39,37], [32.01,40], [36,40], [30,31],
	],
}

const REGION_COUNT_KEY = {
	India: "india",
	Asia: "asia",
	"Middle East": "middle_east",
	Africa: "africa",
	Europe: "europe",
	Americas: "americas",
}

function isSelected(region) {
	return (props.selectedRegions || []).includes(region)
}

function visiblePoints(region, points) {
	const counts = props.regionCounts
	// no data yet (resource still loading) — show the full pool so the map
	// isn't empty while waiting on the first response
	if (!counts) return points

	const count = counts[REGION_COUNT_KEY[region]] || 0
	if (count <= 0) return []

	const maxCount = Math.max(0, ...Object.values(counts))
	if (maxCount <= 0) return []

	const slots = Math.round((count / maxCount) * points.length)
	return points.slice(0, Math.min(Math.max(MIN_DOTS, slots), points.length))
}
</script>

<template>
	<svg viewBox="0 0 119 60" class="world-map-pins" preserveAspectRatio="xMidYMid meet">
		<image :href="IMAGE_URL" x="0" y="0" width="119" height="60" />

		<g v-for="(points, region) in REGION_DOTS" :key="region">
			<circle
				v-for="([x, y], i) in visiblePoints(region, points)"
				:key="`${region}-${i}`"
				:cx="x"
				:cy="y"
				:r="isSelected(region) ? SELECTED_R : DOT_R"
				:class="['map-dot', { 'map-dot--selected': isSelected(region) }]"
			/>
		</g>
	</svg>
</template>

<style scoped>
.world-map-pins {
	width: 100%;
	height: auto;
	display: block;
}

.map-dot {
	fill: var(--ink-gray-7, #525252);
	transition: r 0.15s ease, fill 0.15s ease;
}

.map-dot--selected {
	fill: var(--ink-gray-9, #171717);
}

@media (prefers-reduced-motion: reduce) {
	.map-dot {
		transition: none;
	}
}
</style>
