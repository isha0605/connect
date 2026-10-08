// The Starter Pack recommendation: which packs the questionnaire's answers point to
// and why, the packs themselves (tick to add, "View details" for scope), and a basket
// that hands over to the checkout page. The answers arrive in the URL;
// the rules that read them live in @app/utils/recommendation.

import { computed, ref } from "vue"
import {
	CUSTOM_IF,
	HOW_IT_WORKS,
	INCLUDED,
	NOT_INCLUDED,
	OUR_NEEDS,
	answersFromProject,
	answersFromQuery,
	answersToQuery,
	directoryQuery,
	recommend,
} from "@app/utils/recommendation"
import { packBasket } from "@app/utils/packBasket"
import { projectDialog, projectPath } from "@app/utils/projectDialog"

export default function setup(context) {
	const { route, router, call, toast, partnerCountries, pickedPacks } = context
	const basket = packBasket(context)
	const { packs } = basket

	// Two ways in: the questionnaire's answers in the URL, or ?project=CP-… for a draft
	// project from the Projects page, whose answers are fetched.
	const projectName = String(route.query.project || "")
	const project = ref(null)
	const answers = ref(projectName ? null : answersFromQuery(route.query))
	const recommendation = computed(() => (answers.value ? recommend(answers.value) : null))
	const recommended = computed(() =>
		recommendation.value?.verdict === "packs" ? recommendation.value.packs : [],
	)

	// Start with the recommended packs ticked; the customer can change that freely.
	function tickRecommended() {
		pickedPacks.value = recommended.value.map((p) => p.key)
	}
	tickRecommended()

	if (projectName) {
		call("connect.api.projects.get_project", { name: projectName })
			.then((data) => {
				// Already paid for: the project now lives on its implementation steps.
				if (data.order) {
					router.replace({ path: "/starter-pack-implementation", query: { order: data.order } })
					return
				}
				project.value = data
				answers.value = answersFromProject(data)
				tickRecommended()
			})
			.catch(() => toast.error("Couldn't open that project."))
	}

	const inProject = !!projectName
	const projectTitle = computed(() => project.value?.project_name || "Project")
	const breadcrumbItems = computed(() => [
		{ label: "Projects", route: { path: "/projects" } },
		{ label: projectTitle.value },
	])

	const headline = computed(() => {
		if (!recommended.value.length) return "Starter Packs"
		return recommended.value.length > 1 ? "We recommend these Starter Packs" : "We recommend a Starter Pack"
	})

	// A "Recommended" badge only means something when it singles packs out.
	function isRecommended(key) {
		return recommended.value.length < packs.value.length && recommended.value.some((p) => p.key === key)
	}

	// "Look at the packs anyway" from the custom implementation page lands here with answers
	// that recommend custom. Then this section says what we'd have recommended instead of
	// arguing for packs it didn't pick. Read off the answers, so it survives a reload.
	const packsAnyway = computed(() => recommendation.value?.verdict === "custom")
	const whyTitle = computed(() =>
		packsAnyway.value ? "What we'd have recommended" : "Why we think this is the best choice for you",
	)

	const whyReasons = computed(() =>
		recommendation.value?.verdict === "packs" ? recommendation.value.reasons : [],
	)
	const packReasons = computed(() =>
		recommended.value.map((r) => ({
			key: r.key,
			name: packs.value.find((p) => p.pack_key === r.key)?.pack_name || "",
			reason: `${r.reason}.`,
		})),
	)
	const packReasonsTitle = computed(() =>
		recommended.value.length > 1 ? "Why we recommend these packs" : "Why we recommend this pack",
	)

	// For a project, "Change my answers" edits the draft right here; if the new answers
	// rule a pack out, the custom implementation page takes over.
	const dialog = projectDialog(context, {
		onSaved: (saved) => {
			if (saved.verdict === "packs") {
				project.value = saved
				answers.value = answersFromProject(saved)
				tickRecommended()
				return
			}
			router.push(projectPath({ kind: "project", project: saved.name, verdict: saved.verdict }))
		},
	})

	function changeAnswers() {
		if (inProject) {
			if (project.value) dialog.editProject(project.value)
			return
		}
		router.push({ path: "/find-partners-redesign", query: answersToQuery(answers.value || {}) })
	}

	function deleteProject() {
		call("connect.api.projects.delete_project", { name: projectName })
			.then(() => router.push("/projects"))
			.catch(() => toast.error("Couldn't delete the project."))
	}

	const projectMenu = [
		{ label: "Change my answers", icon: "lucide-pencil", onClick: changeAnswers },
		{ label: "Delete project", icon: "lucide-trash-2", onClick: deleteProject },
	]

	// Under "Consider a custom implementation if": someone who came here from the custom
	// page goes back to it; anyone else is offered partner quotes.
	const customSectionAction = computed(() =>
		packsAnyway.value ? "Back to what we recommend" : "Get quotes from partners instead",
	)

	function customSectionClick() {
		if (packsAnyway.value) {
			router.push({ path: "/custom-implementation", query: { project: projectName } })
			return
		}
		getQuotes()
	}

	function getQuotes() {
		router.push({
			path: "/partner-directory-redesign",
			query: directoryQuery(answers.value || {}, partnerCountries.data || []),
		})
	}

	return {
		...dialog,
		...basket,
		howItWorks: HOW_IT_WORKS,
		included: INCLUDED,
		notIncluded: NOT_INCLUDED,
		customIf: CUSTOM_IF,
		ourNeeds: OUR_NEEDS,
		hasAnswers: computed(() => !!answers.value),
		packsAnyway,
		whyTitle,
		customSectionAction,
		customSectionClick,
		inProject,
		projectTitle,
		breadcrumbItems,
		projectMenu,
		headline,
		isRecommended,
		whyReasons,
		packReasons,
		packReasonsTitle,
		changeAnswers,
		getQuotes,
	}
}
