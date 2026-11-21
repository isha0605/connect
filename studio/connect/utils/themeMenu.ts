import { computed } from "vue"
import { useColorScheme } from "frappe-ui"

const THEMES = [
	{ value: "light", label: "Light" },
	{ value: "dark", label: "Dark" },
	{ value: "system", label: "System" },
]

/**
 * The sidebar's Theme menu item: Light, Dark or System, kept in the browser by frappe-ui, so it
 * works signed in or not. `icons` returns the lucide names by item (theme, light, dark, system);
 * they're written in the sidebar's block JSON, since Studio bundles only the icons it finds there.
 */
export function useThemeMenu(icons: () => Record<string, string>) {
	const { colorScheme, setColorScheme } = useColorScheme()
	return computed(() => ({
		label: "Theme",
		icon: icons().theme,
		submenu: THEMES.map((theme) => ({
			label: theme.label,
			icon: icons()[theme.value],
			selected: colorScheme.value === theme.value,
			onClick: () => setColorScheme(theme.value),
		})),
	}))
}
