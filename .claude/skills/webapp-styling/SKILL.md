---
name: webapp-styling
description: Styling conventions for apps/webapp — Tailwind v4, the dark slate palette, shared primitives in src/ui.tsx, badge tones, and when to extract a component. Use whenever writing, modifying, or reviewing component styling in the webapp — picking a primitive vs writing utilities, conditional classes, hover/focus/disabled states, layout, spacing, or color choices.
user-invocable: false
---

# Webapp Styling

**Tailwind only.** Tailwind v4 through the `@tailwindcss/vite` plugin; the entire CSS surface is
`@import "tailwindcss"` in `src/index.css`. No tailwind.config file, no component CSS files, no inline
`style` attributes, no CSS modules. If you are writing a `.css` file for a component, you are off-pattern.

## Priority order

1. Use a shared primitive from `src/ui.tsx` when one fits
2. Compose Tailwind utilities inline, conditional classes via template literals
3. Extract a new primitive into `src/ui.tsx` only when the extraction rule below is met

## Shared primitives

Check `src/ui.tsx` before writing inline utilities for a common element:

| Primitive | Use for |
|-----------|---------|
| `Page` | Every route: title, optional header actions, padding |
| `Table` / `Td` | All tabular resource data; `Td mono` for ids, tokens, numbers |
| `Badge` | Status indication, tones `ok` / `warn` / `err` |
| `Button` | Every action, `danger` for destructive ones; never a bare styled `<button>` |
| `inputClass` | Every `<input>` and `<select>` |
| `QueryStatus` | Loading / error / empty rendering on every query-backed page |

## Palette

The console is dark, slate plus one accent. Stay inside it:

| Role | Classes |
|------|---------|
| Page background | `bg-slate-950` |
| Panel / table header background | `bg-slate-900` |
| Borders and dividers | `border-slate-800`, `divide-slate-800` |
| Primary text | `text-slate-100` |
| Body text | `text-slate-300` |
| Secondary text | `text-slate-400` |
| Muted / placeholder | `text-slate-500`, `text-slate-600` |
| Accent (actions, active nav) | `indigo-600` background, `indigo-950`/`indigo-300` for active states |
| Positive | `emerald-950` / `emerald-400` / ring `emerald-800` |
| Warning | `amber-950` / `amber-400` / ring `amber-800` |
| Negative | `red-950` / `red-400` / ring `red-800` |

Semantic colors follow the Badge tone shape: dark background, bright text, matching ring.

## Common patterns

```tsx
// Pill (non-status tag, e.g. capabilities)
<span className="inline-flex rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-300 ring-1 ring-slate-700">{c}</span>

// Row hover
<tr className="hover:bg-slate-900/50">

// Callout (success banner, adapt the tone)
<div className="rounded-lg border border-emerald-800 bg-emerald-950/50 px-4 py-3">

// Conditional classes
<div className={`base-classes ${isActive ? 'active-classes' : 'inactive-classes'}`}>
```

## When to extract into src/ui.tsx

Extract when the same combination of four or more utilities appears three or more times and represents
a reusable concept (pill, callout, form row). Accept an optional `className` and merge it after the
base classes. Below that threshold, keep utilities inline; premature primitives are harder to delete
than repeated strings.

## Do not

1. Hardcode colors outside the palette; `bg-[#1e293b]` when `bg-slate-800` exists is a bug
2. Style a native `<button>` when `Button` fits
3. Add a CSS file, inline `style`, or a Tailwind config to solve a one-component problem
4. Introduce a component library (shadcn, Radix, MUI) without discussing it first; the console is small and hand-rolled on purpose
5. Repeat a complex class string across files instead of extracting once the threshold is met
