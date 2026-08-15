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

1. Reuse an application primitive from `src/components/ui/elements.tsx` or a product composition from `src/components/shared/`
2. Extend that component with a focused prop or variant when the concept already exists but one state is missing
3. Compose a vendored shadcn primitive from `src/components/ui/` when the accessible behavior is not exposed by `elements.tsx`
4. Compose Tailwind utilities inline only for genuinely page-specific layout and presentation, using `cn()` from `src/lib/utils.ts`
5. Extract a new application primitive or shared composition when the extraction rules below are met

## Component ownership

| Location | Owns |
|----------|------|
| `components/ui/*.tsx` | Vendored low-level behavior and accessibility such as Dialog, Select, RadioGroup, Tabs, Sheet, and InputGroup |
| `components/ui/elements.tsx` | The console's themed application API, variants, and wrappers around vendored primitives |
| `components/shared/` | Reusable product-level compositions such as FormDialog, DataTable, EmptyState, and resource panels |
| `pages/` | Page-specific assembly and layout only |

Application code never imports `@radix-ui` directly. Vendored primitive modules own Radix integration,
and `elements.tsx` composes those local primitives. A native element is appropriate for semantic layout
or prose, not as a custom replacement for an existing interactive component.

## Reuse check before writing markup

1. Search `elements.tsx`, `components/shared/`, and `components/ui/` by behavior, not only by the name you expected
2. Search current callsites to see how the closest component is configured and styled
3. Reuse it unchanged when it fits; do not clone its classes into the page
4. Add a focused variant or prop when the missing state belongs to the existing component's concept
5. Add or compose a new shared component when the behavior has multiple callers or requires centralized accessibility
6. Keep it local only when it is simple, presentational, page-specific, and has no existing equivalent

## Shared primitives

Check `src/components/ui/elements.tsx` before writing inline utilities for a common element:

| Primitive | Use for |
|-----------|---------|
| `Button` | Every action; variants `default` / `secondary` / `outline` / `ghost` / `destructive`, sizes `sm` / `lg` / `icon`. Never a bare styled `<button>` |
| `Input` / `Label` | Every text field and its label |
| `Dropdown` | Themed single-value selection and attached actions |
| `Badge` | Status indication; variants `default` / `secondary` / `outline` / `success` / `destructive` / `mono` |
| `Card` (+ `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter`) | Every panel that groups content |
| `Table` (+ `TableHeader`, `TableBody`, `TableRow`, `TableHead`, `TableCell`) | All tabular resource data |
| `Modal` | Form and content dialogs; takes `open`, `onOpenChange`, `title`, optional `description` |
| `ConfirmButton` | Destructive or consequential actions that require confirmation |
| `Tabs` (+ `TabsList`, `TabsTrigger`, `TabsContent`) | In-page sectioning |
| `Alert` (+ `AlertTitle`, `AlertDescription`) | Inline callouts and recoverable feedback |
| `Avatar` (+ `AvatarImage`, `AvatarFallback`) | User identity |
| `Sheet` (+ content, header, title, description) | Side panels and mobile navigation |

The rest of `src/components/ui/` is the vendored shadcn set. Import from it, do not edit it by hand.

Check `src/components/shared/` before composing product patterns:

| Composition | Use for |
|-------------|---------|
| `FormDialog` | Validated create and edit forms in a modal |
| `DataTable` | Resource lists with consistent loading, empty, and table presentation |
| `LoadingState` / `ErrorState` / `EmptyState` | Observable query states |
| `PageShell` | Standard page width, spacing, title, and actions |
| `MembersPanel` | Membership lists and mutations |
| `ApiKeysTable` | Instance and workspace key lists and revocation |

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

## When to extract

Extract into `elements.tsx` when the concept is a general interaction or visual primitive, including
an application wrapper around accessible vendored behavior. Do this immediately for dialog, select,
radio, tabs, tooltip, menu, and similar behavior that must not diverge between pages.

Extract into `components/shared/` when a stable product-level composition reaches its second real
caller, or when the current change introduces that second caller. Examples include a form dialog,
search control, data table, empty state, or resource panel. Accept an optional `className` when layout
customization is useful and merge it through `cn()` after the base classes.

A repeated combination of four or more utilities across three callsites is also an extraction signal.
Do not create speculative generic components with no concrete caller, but do not wait for a third copy
of known shared behavior before centralizing it.

Import counts are not enough to declare a primitive unused. Before deleting one, check whether
`elements.tsx` or a shared component manually recreates the same behavior. Migrate that wrapper to
compose the primitive first, then remove only what remains genuinely unnecessary.

## Do not

1. Hardcode colors outside the token set; `bg-[#0a0a0a]` when `bg-background` exists is a bug
2. Reach for a raw slate/zinc/neutral scale where a semantic token says the same thing
3. Style a native `<button>` when `Button` fits
4. Add a CSS file, inline `style`, or a Tailwind config to solve a one-component problem
5. Hand-edit a vendored shadcn component in `src/components/ui/`; wrap it or add to `elements.tsx` instead
6. Repeat a complex class string across files instead of extracting once the threshold is met
7. Import Radix from a page or application wrapper instead of composing the local vendored primitive
8. Rebuild an existing component's behavior with a styled native element because its current API lacks one minor variant
