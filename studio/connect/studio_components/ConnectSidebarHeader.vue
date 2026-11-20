<script setup>
// The sidebar's company menu: the company the person works for, its settings, the Frappe staff who
// look after a partner, Switch company and Give feedback. Settings, Switch company and feedback
// open their own dialogs (ConnectSettings, SwitchCompanyDialog, ConnectFeedback) through window events.
import { computed } from "vue"
import { SidebarHeader } from "frappe-ui"

const props = defineProps({
	// connect.api.account.get_my_context
	context: { type: Object, default: null },
	// Menu icons, by item. They're named in the sidebar's block JSON because Studio's build bundles only
	// the lucide icons it finds there, not those in a component's script.
	icons: { type: Object, default: () => ({}) },
})

const send = (name, detail) => () => window.dispatchEvent(new CustomEvent(name, { detail }))

const partner = computed(() => props.context?.partner || null)
const customer = computed(() => props.context?.customer || null)
const companyName = computed(() => partner.value?.company_name || customer.value?.customer_name || props.context?.full_name || "")

// A partner's settings open on its team; a customer's on its company details.
const settings = computed(() => {
	if (partner.value) return { label: "Firm settings", tab: "users" }
	if (customer.value) return { label: "Company settings", tab: "company" }
	return { label: "Settings", tab: "profile" }
})

const menuItems = computed(() => {
	const managers = partner.value?.managers || []
	return [
		{ label: settings.value.label, icon: props.icons.settings, onClick: send("connect:open-settings", { tab: settings.value.tab }) },
		managers.length && {
			label: "Partner managers",
			icon: props.icons.managers,
			submenu: managers.map((manager) => ({
				label: manager.full_name || manager.email,
				icon: props.icons.email,
				onClick: () => (window.location.href = `mailto:${manager.email}`),
			})),
		},
		partner.value?.can_switch && { label: "Switch company", icon: props.icons.switch, onClick: send("connect:switch-company") },
		{ label: "Give feedback", icon: props.icons.feedback, onClick: send("connect:open-feedback") },
	].filter(Boolean)
})
</script>

<template>
	<SidebarHeader title="Frappe Connect" :subtitle="companyName" logo="/assets/connect/images/connect-logo.svg" :menu-items="menuItems" />
</template>
