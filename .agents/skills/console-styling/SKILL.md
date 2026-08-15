---
name: console-styling
description: Styling conventions for apps/console — Tailwind v4, the semantic token theme, shared primitives in components/ui/elements.tsx, badge variants, and when to extract a component. Use whenever writing, modifying, or reviewing component styling in the console — picking a primitive vs writing utilities, conditional classes, hover/focus/disabled states, layout, spacing, or color choices.
user-invocable: false
---

# Console Styling

**Tailwind only.** Tailwind v4 through the `@tailwindcss/vite` plugin; the whole CSS surface is
`src/index.css`, which imports Tailwind and declares the theme. No tailwind.config file, no component
CSS files, no inline `style` attributes, no CSS modules. If you are writing a `.css` file for a
component, you are off-pattern.

## Priority order

1. Use a shared primitive from `src/components/ui/elements.tsx` when one fits
2. Use a vendored shadcn component from `src/components/ui/` when `elements.tsx` has no equivalent
3. Compose Tailwind utilities inline, conditional classes through `cn()` from `src/lib/utils.ts`
4. Extract a new primitive into `elements.tsx` only when the extraction rule below is met

## Shared primitives

Check `src/components/ui/elements.tsx` before writing inline utilities for a common element:

| Primitive | Use for |
|-----------|---------|
| `Button` | Every action; variants `default` / `secondary` / `outline` / `ghost` / `destructive`, sizes `sm` / `lg` / `icon`. Never a bare styled `<button>` |
| `Input` / `Label` | Every text field and its label |
| `Badge` | Status indication; variants `default` / `secondary` / `outline` / `success` / `destructive` / `mono` |
| `Card` (+ `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter`) | Every panel that groups content |
| `Table` (+ `TableHeader`, `TableBody`, `TableRow`, `TableHead`, `TableCell`) | All tabular resource data |
| `Modal` | Every dialog; takes `open`, `onOpenChange`, `title`, optional `description` |
| `Tabs` (+ `TabsList`, `TabsTrigger`, `TabsContent`) | In-page sectioning |

The rest of `src/components/ui/` is the vendored shadcn set. Import from it, do not edit it by hand.

## Palette

The theme is semantic tokens declared in `src/index.css`, not raw color scales. Style against the
token, never the hex or the slate/zinc number behind it:

| Role | Classes |
|------|---------|
| Page background | `bg-background` |
| Panel / card background | `bg-card`, with `border-card-border` |
| Borders and dividers | `border-border` |
| Primary text | `text-foreground` |
| Secondary and placeholder text | `text-muted-foreground` |
| Muted surface (table headers, hovers, chips) | `bg-muted`, `bg-muted/40`, `bg-muted/50` |
| Primary action | `bg-primary text-primary-foreground` |
| Secondary action | `bg-secondary text-secondary-foreground` |
| Focus ring | `ring-ring` through `focus-visible:ring-1` |
| Sidebar | `bg-sidebar`, `text-sidebar-foreground`, `border-sidebar-border`, active `bg-sidebar-accent` |
| Negative | `text-destructive`, `bg-destructive/10`, `border-destructive/30` |

The palette uses near-black, violet-tinted surfaces with violet as the primary accent. Preserve that
accent across primary actions, focus rings, active navigation, badges, and the ambient page glow.
Positive and warning states use the `success` and `warning` tokens at low alpha for surfaces and full
strength for text and icons. Everything else uses a semantic token.

Type is `font-sans` with `font-mono` for ids, tokens, and machine values.

## Common patterns

```tsx
// Conditional classes
<div className={cn('base-classes', isActive && 'active-classes')}>

// Callout (warning tone; swap the color for the semantic you need)
<div className="p-4 bg-amber-500/10 border border-amber-500/20 rounded-lg flex gap-3 text-amber-400">

// Machine value in a table cell
<TableCell className="font-mono text-xs text-muted-foreground">{org.id}</TableCell>

// Page shell
<div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6">
```

## When to extract into elements.tsx

Extract when the same combination of four or more utilities appears three or more times and represents
a reusable concept (pill, callout, form row). Accept an optional `className` and merge it through `cn()`
after the base classes. Below that threshold, keep utilities inline; premature primitives are harder to
delete than repeated strings.

## Do not

1. Hardcode colors outside the token set; `bg-[#0a0a0a]` when `bg-background` exists is a bug
2. Reach for a raw slate/zinc/neutral scale where a semantic token says the same thing
3. Style a native `<button>` when `Button` fits
4. Add a CSS file, inline `style`, or a Tailwind config to solve a one-component problem
5. Hand-edit a vendored shadcn component in `src/components/ui/`; wrap it or add to `elements.tsx` instead
6. Repeat a complex class string across files instead of extracting once the threshold is met
