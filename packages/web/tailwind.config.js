/** @type {import('tailwindcss').Config} */
export default {
	content: ['./src/**/*.{html,js,svelte,ts}'],
	theme: {
		extend: {
			colors: {
				'of-bg': '#1e1e2e',
				'of-bg-alt': '#2d2d3f',
				'of-panel': '#252535',
				'of-border': '#3d3d5c',
				'of-accent': '#7aa2f7',
				'of-text': '#c0caf5',
				'of-text-dim': '#a9b1d6',
				'of-success': '#9ece6a',
				'of-warning': '#e0af68',
				'of-error': '#f7768e',
			},
			fontFamily: {
				mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
			},
		},
	},
	plugins: [],
};
