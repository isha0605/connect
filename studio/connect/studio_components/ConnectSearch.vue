<script setup>
// The sidebar's Search item and the search dialog it opens (also Ctrl/Cmd+K), for an approved partner
// or a signed-in customer. It searches the lists the person's own pages load, so it never shows more
// than those pages do, and it matches only text those pages show: an anonymous lead's company is
// "Anonymous company" here too, so searching a guessed name can't confirm it.
import { computed, getCurrentInstance, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { Avatar, Dialog, LoadingIndicator, SidebarItem, call } from "frappe-ui"
import { projectPath } from "@app/utils/projectDialog"

const props = defineProps({
	context: { type: Object, default: null },
})

// Each sidebar's items, in its order, with the same visibility.
const PARTNER_PAGES = [
	{ label: "Leads", icon: "lucide-users", route: "/leads", isShown: (context) => context.partner.can_see_leads },
	{ label: "Customers", icon: "lucide-building-2", route: "/customers", isShown: (context) => context.partner.can_see_customers },
	{ label: "Partnership", icon: "lucide-handshake", route: "/partner-overview" },
	{ label: "Certifications", icon: "lucide-award", route: "/partner-certifications" },
	{ label: "Audits", icon: "lucide-clipboard-check", route: "/partner-audits" },
	{ label: "Public profile", icon: "lucide-store", route: "/partner-listing" },
	{ label: "Invoices", icon: "lucide-receipt", route: "/partner-invoicing" },
]
const CUSTOMER_PAGES = [
	{ label: "Projects", icon: "lucide-briefcase", route: "/projects", isShown: (context) => context.has_projects },
	{ label: "Messages", icon: "lucide-inbox", route: "/messaging" },
	{ label: "Partners", icon: "lucide-building-2", route: "/partner-directory-redesign" },
]

// What each kind of user searches: the lists to load and the result groups found in them.
const SEARCHES = {
	partner: {
		placeholder: "Search people, leads, customers and pages",
		pages: PARTNER_PAGES,
		load: loadPartnerLists,
		results: (lists, matches) => [
			{ title: "People", rows: lists.team.filter((m) => matches(m.full_name, m.user)).map(personRow) },
			{ title: "Leads", rows: lists.leads.filter((l) => matches(...leadText(l))).map(leadRow) },
			{ title: "Customers", rows: lists.customers.filter((c) => matches(c.company)).map(customerRow) },
		],
	},
	customer: {
		placeholder: "Search projects, partners and pages",
		pages: CUSTOMER_PAGES,
		load: loadCustomerLists,
		results: (lists, matches) => [
			{ title: "Projects", rows: lists.projects.filter((p) => matches(p.project_title, p.company_name)).map(projectRow) },
			{ title: "Partners", rows: lists.partners.filter((p) => matches(p.company_name)).map(partnerRow) },
		],
	},
}
const ROWS_PER_GROUP = 8

const open = ref(false)
const query = ref("")
const activeIndex = ref(0)
const loading = ref(false)
const hasLoadError = ref(false)
const lists = ref(null)
const router = getCurrentInstance()?.appContext.config.globalProperties.$router

const shortcut = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘K" : "Ctrl K"

// A partner gets search once approved; anyone else signed in is a customer, as the sidebar decides.
const search = computed(() => {
	const context = props.context
	if (context?.partner) return context.partner.is_approved ? SEARCHES.partner : null
	return context?.user && context.user !== "Guest" ? SEARCHES.customer : null
})

// Nothing typed: only the pages to go to. A query searches the loaded lists and the pages.
const groups = computed(() => {
	const text = query.value.trim().toLowerCase()
	if (!text) return numbered([{ title: "Go to", rows: pageRows() }])

	const matches = (...values) => values.some((value) => (value || "").toLowerCase().includes(text))
	const found = [
		...(lists.value ? search.value.results(lists.value, matches) : []),
		{ title: "Pages", rows: pageRows().filter((row) => matches(row.label)) },
	]
	return numbered(
		found.map((group) => ({ ...group, rows: group.rows.slice(0, ROWS_PER_GROUP) })).filter((group) => group.rows.length),
	)
})

const rows = computed(() => groups.value.flatMap((group) => group.rows))

watch(query, () => {
	activeIndex.value = 0
})

async function openSearch() {
	if (!search.value) return
	query.value = ""
	activeIndex.value = 0
	open.value = true
	await load()
}

// Ctrl on Windows/Linux, ⌘ on macOS. Claimed from the browser, where Ctrl+K searches the address bar.
function onShortcut(event) {
	if (!search.value || !(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return
	if (event.key.toLowerCase() !== "k") return
	event.preventDefault()
	if (open.value) open.value = false
	else openSearch()
}

function onKeydown(event) {
	if (event.key === "ArrowDown" || event.key === "ArrowUp") {
		event.preventDefault()
		moveActive(event.key === "ArrowDown" ? 1 : -1)
	} else if (event.key === "Enter") {
		event.preventDefault()
		select(rows.value[activeIndex.value])
	}
}

function moveActive(step) {
	const count = rows.value.length
	if (!count) return
	activeIndex.value = (activeIndex.value + step + count) % count
	nextTick(() => document.getElementById(optionId(activeIndex.value))?.scrollIntoView({ block: "nearest" }))
}

function select(row) {
	if (!row) return
	open.value = false
	if (row.user) {
		window.dispatchEvent(new CustomEvent("connect:open-settings", { detail: { tab: "users", user: row.user } }))
		return
	}
	if (router && router.currentRoute.value.fullPath !== router.resolve(row.route).fullPath) router.push(row.route)
}

async function load() {
	loading.value = true
	hasLoadError.value = false
	lists.value = await search.value.load()
	loading.value = false
}

async function loadPartnerLists() {
	const partner = props.context.partner
	const [team, leads, customers] = await Promise.all([
		fetchList("connect.api.account.get_my_team", (rows) => rows.filter((m) => !m.is_removed)),
		partner.can_see_leads ? fetchList("connect.api.leads.list_leads", (data) => data.leads) : [],
		partner.can_see_customers ? fetchList("connect.api.partner_customers.list_customers", (data) => data.customers) : [],
	])
	return { team, leads, customers }
}

// The partners are the directory's own list, the one the Partners page shows.
async function loadCustomerLists() {
	const [projects, partners] = await Promise.all([
		fetchList("connect.api.projects.list_projects", (rows) => rows),
		fetchList("connect.api.partner.search_partners", (rows) => rows),
	])
	return { projects, partners }
}

// A list that fails to load stays empty rather than failing the whole search.
async function fetchList(method, pick) {
	try {
		return pick(await call(method)) || []
	} catch {
		hasLoadError.value = true
		return []
	}
}

function pageRows() {
	return search.value.pages
		.filter((page) => !page.isShown || page.isShown(props.context))
		.map((page) => ({ key: "page:" + page.route, label: page.label, icon: page.icon, route: page.route }))
}

function personRow(member) {
	return {
		key: "person:" + member.user,
		label: member.full_name || member.user,
		image: member.user_image,
		hint: member.access_level,
		user: member.user,
	}
}

// A lead is shown by its newest requirement, but any of its requirements can find it.
function leadText(lead) {
	return [lead.project_name, lead.company, ...(lead.requirement_names || [])]
}

function leadRow(lead) {
	return {
		key: "lead:" + lead.name,
		label: lead.project_name || lead.company,
		icon: "lucide-target",
		hint: lead.company,
		route: "/leads/" + encodeURIComponent(lead.name),
	}
}

function customerRow(customer) {
	return {
		key: "customer:" + customer.name,
		label: customer.company,
		icon: "lucide-building-2",
		hint: customer.stage,
		route: "/customers/" + encodeURIComponent(customer.name),
	}
}

// A project and a paid Starter Pack open different pages, as on the Projects page.
function projectRow(project) {
	return {
		key: "project:" + (project.order || project.project),
		label: project.project_title,
		icon: "lucide-briefcase",
		hint: project.company_name,
		route: projectPath(project),
	}
}

function partnerRow(partner) {
	return {
		key: "partner:" + partner.name,
		label: partner.company_name,
		icon: "lucide-building-2",
		route: "/partner-profile-redesign/" + encodeURIComponent(partner.name),
	}
}

// One running index across groups, so the arrow keys move through every group in turn.
function numbered(found) {
	let index = 0
	return found.map((group) => ({ ...group, rows: group.rows.map((row) => ({ ...row, index: index++ })) }))
}

function optionId(index) {
	return "connect-search-option-" + index
}

onMounted(() => window.addEventListener("keydown", onShortcut))
onBeforeUnmount(() => window.removeEventListener("keydown", onShortcut))
</script>

<template>
	<div v-if="search">
		<SidebarItem label="Search" :active="false" @click="openSearch">
			<template #prefix>
				<span class="lucide-search size-4 text-ink-gray-6" aria-hidden="true" />
			</template>
			<template #suffix>
				<span class="mr-2 text-sm text-ink-gray-4">{{ shortcut }}</span>
			</template>
		</SidebarItem>

		<Dialog v-model:open="open" size="xl" bare>
			<div class="flex items-center gap-2 border-b border-outline-gray-1 px-4">
				<span class="lucide-search size-4 shrink-0 text-ink-gray-5" aria-hidden="true" />
				<input
					v-model="query"
					autofocus
					type="text"
					role="combobox"
					aria-label="Search"
					aria-controls="connect-search-results"
					:aria-expanded="true"
					:aria-activedescendant="rows.length ? optionId(activeIndex) : undefined"
					:placeholder="search.placeholder"
					class="h-12 w-full border-0 bg-transparent px-0 text-base text-ink-gray-8 placeholder:text-ink-gray-4 focus:ring-0"
					@keydown="onKeydown"
				/>
			</div>

			<!-- Same thin scrollbar as the rest of Connect's scrolling lists. -->
			<div
				id="connect-search-results"
				role="listbox"
				aria-label="Search results"
				class="max-h-[60vh] overflow-y-auto p-2"
				style="scrollbar-width: thin; scrollbar-color: var(--outline-gray-3) transparent"
			>
				<section v-for="group in groups" :key="group.title" class="mb-2 last:mb-0">
					<h3 class="px-3 pb-1 pt-2 text-sm text-ink-gray-5">{{ group.title }}</h3>
					<button
						v-for="row in group.rows"
						:id="optionId(row.index)"
						:key="row.key"
						type="button"
						role="option"
						tabindex="-1"
						:aria-selected="row.index === activeIndex"
						class="flex w-full items-center gap-3 rounded px-3 py-2 text-left"
						:class="row.index === activeIndex ? 'bg-surface-gray-2' : ''"
						@mouseenter="activeIndex = row.index"
						@click="select(row)"
					>
						<Avatar v-if="row.user" :label="row.label" :image="row.image" size="sm" class="shrink-0" />
						<span v-else :class="row.icon" class="size-4 shrink-0 text-ink-gray-6" aria-hidden="true" />
						<span class="min-w-0 flex-1 truncate text-base text-ink-gray-8">{{ row.label }}</span>
						<span v-if="row.hint" class="shrink-0 text-sm text-ink-gray-5">{{ row.hint }}</span>
					</button>
				</section>

				<div v-if="loading && query.trim()" class="flex justify-center py-4">
					<LoadingIndicator class="size-4 text-ink-gray-5" />
				</div>
				<p v-else-if="!rows.length" class="px-3 py-6 text-center text-base text-ink-gray-5">
					No results for “{{ query.trim() }}”
				</p>
				<p v-if="hasLoadError" class="px-3 py-2 text-sm text-ink-red-4">
					Some results couldn't be loaded. Close search and try again.
				</p>
			</div>
		</Dialog>
	</div>
</template>
