<script setup>
// A partner's monthly Frappe Cloud revenue as a soft area, edge to edge. Each month shows its amount
// on hover or focus, and screen readers get the same numbers as a table.

import { computed, ref, useId } from "vue"

const props = defineProps({
	// [{ month: "Nov 2026", amount: 504640 }], oldest first
	points: { type: Array, default: () => [] },
	currency: { type: String, default: "INR" },
})

// The highest month sits this far below the top, so the line never touches the card's edge.
const HEADROOM = 0.25

const gradientId = `mrr-fill-${useId()}`
const hovered = ref(null)

const money = computed(
	() => new Intl.NumberFormat("en-IN", { style: "currency", currency: props.currency, maximumFractionDigits: 0 }),
)

// The scale starts below the lowest month, not at zero, so a small dip still shows. The lowest month
// sits a third of the way up, keeping the area under the line.
const range = computed(() => {
	const amounts = props.points.map((point) => point.amount)
	const high = Math.max(...amounts, 0)
	const low = Math.min(...amounts, high)
	const floor = high > low ? Math.max(low - (high - low) * 0.5, 0) : 0
	return { floor, span: Math.max(high - floor, 1) }
})

const plotted = computed(() => {
	const last = props.points.length - 1
	const step = last > 0 ? 100 / last : 100
	return props.points.map((point, index) => ({
		...point,
		x: last > 0 ? index * step : 50,
		y: 100 - ((point.amount - range.value.floor) / range.value.span) * (1 - HEADROOM) * 100,
		text: `${point.month}: ${money.value.format(point.amount)}`,
		hitLeft: Math.max(index * step - step / 2, 0),
		hitWidth: index === 0 || index === last ? step / 2 : step,
	}))
})

const line = computed(() => plotted.value.map((point) => `${point.x * 10},${point.y * 10}`).join(" "))
const area = computed(() => (plotted.value.length ? `0,1000 ${line.value} 1000,1000` : ""))
const active = computed(() => (hovered.value === null ? null : plotted.value[hovered.value]))
</script>

<template>
	<div class="mrr">
		<svg aria-hidden="true" viewBox="0 0 1000 1000" preserveAspectRatio="none" class="lines">
			<defs>
				<linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
					<stop offset="0%" class="fill-top" />
					<stop offset="100%" class="fill-bottom" />
				</linearGradient>
			</defs>
			<polygon :points="area" :fill="`url(#${gradientId})`" />
			<polyline :points="line" class="trend" vector-effect="non-scaling-stroke" />
		</svg>
		<template v-if="active">
			<span aria-hidden="true" class="rule" :style="{ left: `${active.x}%` }"></span>
			<span aria-hidden="true" class="dot" :style="{ left: `${active.x}%`, top: `${active.y}%` }"></span>
		</template>
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
			:style="{ left: `${active.x}%`, transform: active.x > 60 ? 'translate(calc(-100% - 8px), 0)' : 'translate(8px, 0)' }"
		>
			<span class="tip-month">{{ active.month }}</span>
			<span class="tip-amount">{{ money.format(active.amount) }}</span>
		</div>

		<table class="visually-hidden">
			<caption>Frappe Cloud MRR by month</caption>
			<tbody>
				<tr v-for="point in points" :key="point.month">
					<th scope="row">{{ point.month }}</th>
					<td>{{ money.format(point.amount) }}</td>
				</tr>
			</tbody>
		</table>
	</div>
</template>

<style scoped>
.mrr {
	position: relative;
	flex: 1;
	min-width: 0;
	min-height: 72px;
}
.lines {
	position: absolute;
	inset: 0;
	width: 100%;
	height: 100%;
}
.fill-top {
	stop-color: var(--ink-blue-5, #0c8ef8);
	stop-opacity: 0.16;
}
.fill-bottom {
	stop-color: var(--ink-blue-5, #0c8ef8);
	stop-opacity: 0;
}
.trend {
	fill: none;
	stroke: var(--ink-blue-5, #0c8ef8);
	stroke-width: 1.5;
	stroke-linejoin: round;
	stroke-linecap: round;
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
	background: var(--ink-blue-5, #0c8ef8);
	box-shadow: 0 0 0 2px var(--surface-white, #ffffff);
}
.hit {
	position: absolute;
	top: 0;
	bottom: 0;
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
	top: 8px;
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
.visually-hidden {
	position: absolute;
	width: 1px;
	height: 1px;
	overflow: hidden;
	clip: rect(0 0 0 0);
	white-space: nowrap;
}
</style>
