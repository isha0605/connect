<script setup>
// Switch company, like Frappe Cloud's Switch Team, for someone on more than one partner's team.
// The sidebar's logo menu opens it with a "connect:switch-company" window event. The server keeps
// the chosen company, and every partner page, permission and chat reads it from there.
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { Alert, Avatar, Badge, Button, Dialog, LoadingIndicator, TextInput, call, toast } from "frappe-ui"

// Where a partner lands after signing in (see connect.auth.accounts): Messaging.
// Below this many companies the list fits without a search box.
const SEARCH_FROM = 6

const open = ref(false)
const companies = ref([])
const user = ref("")
const loading = ref(false)
const loadError = ref("")
const switchingTo = ref("")
const query = ref("")

const current = computed(() => companies.value.find((company) => company.is_current))
const shownCompanies = computed(() => {
	const text = query.value.trim().toLowerCase()
	if (!text) return companies.value
	return companies.value.filter((company) => (company.partner_name || company.partner).toLowerCase().includes(text))
})

const errorText = (e, fallback) => (e && e.messages && e.messages[0]) || (e && e.message) || fallback

async function openDialog() {
	open.value = true
	query.value = ""
	loadError.value = ""
	loading.value = true
	try {
		const [context, list] = await Promise.all([
			call("connect.api.account.get_my_context"),
			call("connect.api.partner.list_my_partners"),
		])
		user.value = context?.user || ""
		companies.value = list || []
	} catch (e) {
		loadError.value = errorText(e, "Could not load your companies")
	} finally {
		loading.value = false
	}
}

async function switchTo(company) {
	if (switchingTo.value) return
	switchingTo.value = company.partner
	try {
		const context = await call("connect.api.partner.switch_partner", { partner: company.partner })
		toast.success(`Now working for ${company.partner_name}`)
		// Pages hold the old company's data, so start again from the new company's partner home.
		window.location.assign(`/connect${context?.partner?.home_route || "/partner-listing"}`)
	} catch (e) {
		toast.error(errorText(e, "Could not switch company"))
		switchingTo.value = ""
	}
}

onMounted(() => window.addEventListener("connect:switch-company", openDialog))
onBeforeUnmount(() => window.removeEventListener("connect:switch-company", openDialog))
</script>

<template>
	<Dialog v-model:open="open" title="Switch company" size="lg">
		<template #default>
			<div class="flex flex-col gap-4">
				<Alert
					:title="`Signed in as ${user}`"
					:description="current ? `Working for ${current.partner_name}` : undefined"
					theme="gray"
				/>

				<TextInput
					v-if="companies.length >= SEARCH_FROM"
					v-model="query"
					type="search"
					placeholder="Search companies"
					aria-label="Search companies"
				>
					<template #prefix>
						<span class="lucide-search size-4 text-ink-gray-5" aria-hidden="true" />
					</template>
				</TextInput>

				<div v-if="loading" class="flex justify-center py-6">
					<LoadingIndicator class="size-5 text-ink-gray-5" />
				</div>

				<p v-else-if="loadError" class="text-p-sm text-ink-red-4" role="alert">{{ loadError }}</p>

				<p v-else-if="!shownCompanies.length" class="py-4 text-center text-p-sm text-ink-gray-5">
					No companies match your search.
				</p>

				<ul v-else class="flex flex-col divide-y divide-outline-gray-1">
					<li
						v-for="company in shownCompanies"
						:key="company.partner"
						class="flex items-center gap-3 py-2.5"
					>
						<Avatar :image="company.logo" :label="company.partner_name" shape="square" size="lg" />
						<div class="flex min-w-0 flex-1 flex-col gap-0.5">
							<span class="truncate text-base font-medium text-ink-gray-8">{{ company.partner_name }}</span>
							<span class="text-sm text-ink-gray-5">{{ company.access_level }}</span>
						</div>
						<Badge v-if="company.is_current" label="Active" theme="green" variant="subtle" />
						<!-- Text in the slot, not `label`: Button's label replaces aria-label, which names the company -->
						<Button
							v-else
							variant="subtle"
							theme="gray"
							:loading="switchingTo === company.partner"
							:disabled="!!switchingTo && switchingTo !== company.partner"
							:aria-label="`Switch to ${company.partner_name}`"
							@click="switchTo(company)"
						>
							Switch
						</Button>
					</li>
				</ul>
			</div>
		</template>
	</Dialog>
</template>
