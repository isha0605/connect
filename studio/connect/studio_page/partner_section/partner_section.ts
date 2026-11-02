// A partner sidebar section that isn't built yet (?section=leads and so on). Each one moves
// to its own page when it's built, and leaves SECTIONS then.

import { computed } from "vue"
import { startTracking } from "@app/utils/tracking"

const SECTIONS = {
	dashboard: { label: "Dashboard", icon: "lucide-layout-dashboard" },
	certifications: { label: "Certifications", icon: "lucide-award" },
	resources: { label: "Resources", icon: "lucide-book-open" },
	contributions: { label: "Contributions", icon: "lucide-git-pull-request" },
	audits: { label: "Audits", icon: "lucide-clipboard-check" },
}

export default function setup(context) {
	startTracking(context)
	const { route } = context

	const section = computed(() => SECTIONS[String(route.query.section || "")] || { label: "Partnership", icon: "lucide-badge-check" })

	return {
		sectionLabel: computed(() => section.value.label),
		sectionIcon: computed(() => section.value.icon),
		breadcrumbItems: computed(() => [{ label: section.value.label }]),
		comingSoonText: computed(() => `${section.value.label} is coming soon. Messages and your Profile work today.`),
	}
}
