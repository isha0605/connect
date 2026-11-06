<script setup>
// A partner's monthly Frappe Cloud revenue as a small line, with the next tier's target as a dashed
// line on top. Each month shows its amount on hover or focus, and the same numbers read as a table.

import { computed, ref } from "vue"

const props = defineProps({
	// [{ month: "Nov 2026", amount: 504640 }], oldest first
	points: { type: Array, default: () => [] },
	// The next tier's MRR; the line reaches the top at this amount.
	target: { type: Number, default: 0 },
	targetLabel: { type: String, default: "" },
	currency: { type: String, default: "INR" },
	updatedLabel: { type: String, default: "" },
})

const view = ref("chart")
const hovered = ref(null)

const money = computed(
	() => new Intl.NumberFormat("en-IN", { style: "currency", currency: props.currency, maximumFractionDigits: 0 }),
)

const top = computed(() => Math.max(props.target, ...props.points.map((point) => point.amount), 1))

const plotted = computed(() => {
	const last = props.points.length - 1
	const step = last > 0 ? 100 / last : 100
	return props.points.map((point, index) => ({
		...point,
		x: last > 0 ? index * step : 50,
		y: 100 - (point.amount / top.value) * 100,
		text: `${point.month}: ${money.value.format(point.amount)}`,
		hitLeft: Math.max(index * step - step / 2, 0),
		hitWidth: index === 0 || index === last ? step / 2 : step,
	}))
})

const line = computed(() => plotted.value.map((point) => `${point.x * 11},${point.y * 10}`).join(" "))
const targetY = computed(() => 100 - (props.target / top.value) * 100)
const lastPoint = computed(() => plotted.value.at(-1))
const firstMonth = computed(() => shortMonth(props.points[0]?.month))
const lastMonth = computed(() => shortMonth(props.points.at(-1)?.month))
const active = computed(() => (hovered.value === null ? null : plotted.value[hovered.value]))
const newestFirst = computed(() => plotted.value.slice().reverse())

function shortMonth(month) {
	return (month || "").replace(" 20", " ’")
}

function toggleView() {
	view.value = view.value === "chart" ? "table" : "chart"
	hovered.value = null
}
</script>

<template>
	<div class="mrr">
		<div v-if="view === 'chart'" class="plot">
			<svg aria-hidden="true" viewBox="0 0 1100 1000" preserveAspectRatio="none" class="lines">
				<line x1="0" y1="1000" x2="1100" y2="1000" class="baseline" vector-effect="non-scaling-stroke" />
				<line
					v-if="target"
					x1="0"
					:y1="targetY * 10"
					x2="1100"
					:y2="targetY * 10"
					class="target"
					vector-effect="non-scaling-stroke"
				/>
				<polyline :points="line" class="trend" vector-effect="non-scaling-stroke" />
			</svg>
			<span v-if="targetLabel" class="target-label" :style="{ top: `${targetY}%` }">{{ targetLabel }}</span>
			<template v-if="active">
				<span aria-hidden="true" class="rule" :style="{ left: `${active.x}%` }"></span>
				<span aria-hidden="true" class="dot" :style="{ left: `${active.x}%`, top: `${active.y}%` }"></span>
			</template>
			<span v-if="lastPoint" aria-hidden="true" class="dot" :style="{ left: `${lastPoint.x}%`, top: `${lastPoint.y}%` }"></span>
			<span class="month first">{{ firstMonth }}</span>
			<span class="month last">{{ lastMonth }}</span>
			<button
				v-for="(point, index) in plotted"
				:key="point.month"
				type="button"
				class="hit"
				:aria-label="point.text"
				:style="{ left: `${point.hitLeft}%`, width: `${point.hitWidth}%` }"
				@mouseenter="hovered = index"
				@focus="hovered = index"
				@mouseleave="hovered = null"
				@blur="hovered = null"
			></button>
			<div
				v-if="active"
				role="status"
				class="tip"
				:style="{ left: `${active.x}%`, transform: active.x > 60 ? 'translate(calc(-100% - 8px), -100%)' : 'translate(8px, -100%)' }"
			>
				<span class="tip-month">{{ active.month }}</span>
				<span class="tip-amount">{{ money.format(active.amount) }}</span>
			</div>
		</div>

		<div v-else class="table" tabindex="0" role="region" aria-label="MRR by month, newest first">
			<table>
				<tbody>
					<tr v-for="point in newestFirst" :key="point.month">
						<th scope="row">{{ point.month }}</th>
						<td>{{ money.format(point.amount) }}</td>
					</tr>
				</tbody>
			</table>
		</div>

		<div class="foot">
			<span>{{ updatedLabel }}</span>
			<button type="button" class="toggle" @click="toggleView">
				{{ view === "chart" ? "View as table" : "View as chart" }}
			</button>
		</div>
	</div>
</template>

<style scoped>
.mrr {
	display: flex;
	flex-direction: column;
	gap: 8px;
	flex: 1;
	min-width: 0;
}
.plot {
	position: relative;
	height: 52px;
	margin: 14px 4px 16px 0;
}
.lines {
	position: absolute;
	inset: 0;
	width: 100%;
	height: 100%;
	overflow: visible;
}
.baseline {
	stroke: var(--outline-gray-2, #e5e5e5);
	stroke-width: 1;
}
.target {
	stroke: var(--ink-gray-4, #a3a3a3);
	stroke-width: 1;
	stroke-dasharray: 4 4;
}
.trend {
	fill: none;
	stroke: var(--ink-blue-3, #2563eb);
	stroke-width: 2;
	stroke-linejoin: round;
	stroke-linecap: round;
}
.target-label {
	position: absolute;
	right: 0;
	transform: translateY(-120%);
	font-size: 11px;
	line-height: 16px;
	color: var(--ink-gray-6, #525252);
}
.rule {
	position: absolute;
	top: 0;
	bottom: 0;
	width: 1px;
	background: var(--outline-gray-2, #e5e5e5);
}
.dot {
	position: absolute;
	width: 8px;
	height: 8px;
	transform: translate(-50%, -50%);
	border-radius: 999px;
	background: var(--ink-blue-3, #2563eb);
	box-shadow: 0 0 0 2px var(--surface-white, #ffffff);
}
.month {
	position: absolute;
	top: 100%;
	margin-top: 4px;
	font-size: 11px;
	line-height: 16px;
	color: var(--ink-gray-6, #525252);
	white-space: nowrap;
}
.month.first {
	left: 0;
}
.month.last {
	right: 0;
}
.hit {
	position: absolute;
	top: -8px;
	bottom: -8px;
	padding: 0;
	border: 0;
	background: transparent;
	cursor: default;
}
.hit:focus-visible {
	outline: 2px solid var(--outline-gray-4, #a3a3a3);
	outline-offset: -2px;
}
.tip {
	position: absolute;
	top: -6px;
	z-index: 1;
	display: flex;
	flex-direction: column;
	gap: 1px;
	padding: 5px 8px;
	border-radius: 6px;
	background: var(--ink-gray-9, #171717);
	color: var(--ink-white, #ffffff);
	font-size: 11px;
	line-height: 16px;
	white-space: nowrap;
	pointer-events: none;
}
.tip-month {
	opacity: 0.8;
}
.tip-amount {
	font-size: 12px;
	font-weight: 600;
}
.table {
	height: 82px;
	overflow-y: auto;
}
.table table {
	width: 100%;
	border-collapse: collapse;
	font-size: 12px;
	line-height: 16px;
}
.table tr {
	border-top: 1px solid var(--outline-gray-1, #f0f0f0);
}
.table th {
	padding: 3px 0;
	text-align: left;
	font-weight: 400;
	color: var(--ink-gray-8, #262626);
}
.table td {
	padding: 3px 0;
	text-align: right;
	font-variant-numeric: tabular-nums;
	color: var(--ink-gray-8, #262626);
}
.foot {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 10px;
	margin-top: auto;
	padding-top: 8px;
	border-top: 1px solid var(--outline-gray-1, #f0f0f0);
	font-size: 11px;
	line-height: 16px;
	color: var(--ink-gray-6, #525252);
}
.toggle {
	padding: 4px 0;
	border: 0;
	background: transparent;
	font: inherit;
	font-size: 12px;
	font-weight: 500;
	color: var(--ink-gray-8, #262626);
	text-decoration: underline;
	text-underline-offset: 2px;
	cursor: pointer;
}
</style>
