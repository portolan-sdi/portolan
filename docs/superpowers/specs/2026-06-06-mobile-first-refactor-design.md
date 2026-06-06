# Mobile-First Refactor Design

Date: 2026-06-06
Status: Approved

## Problem

The Portolan website is desktop-first with zero responsive breakpoints. On mobile (see reference screenshot) the nav overflows, multi-column grids do not collapse, and 56px section padding crushes content. Styling is also inconsistent: font sizes mix arbitrary values (`text-[13px]`, `text-[13.5px]`, `text-[15px]`, `text-[44px]`) with the Tailwind scale (`text-4xl`, `text-sm`), and the header/footer are duplicated across both pages.

The design-token foundation in `globals.css` (colors, radii, spacing, shadows via `@theme inline`) is solid and stays. This refactor makes the site mobile-first and establishes a single source of truth for type and section spacing.

## Decisions (from brainstorming)

- Mobile nav: hamburger drawer.
- Scope: both pages (`home-page`, `quickstart-page`) plus shared `ui/` components.
- Desktop look: preserve the design language, minor polish allowed (unified spacing/type may slightly alter desktop sizes).
- Type scale: semantic tokens in `@theme` (Tailwind v4 `--text-*` auto-generates utilities). Pure utilities, no `@apply`.
- Verification: `pnpm build` + `pnpm lint` clean, then user reviews in browser.

## Constraints (from CLAUDE.md / AGENTS.md)

- Fonts: Archivo (sans) + JetBrains Mono (mono) only.
- Use CSS variables from `globals.css`. Hardcoded hex allowed only in SVG gradients and fixed-dark terminal/map blocks. The terminal stays dark by design; its colors are centralized into tokens but not made theme-aware.
- Corners round: `--p-r-md` (10px) buttons, `--p-r-lg` (16px) cards.
- Tailwind pure utilities, no `@apply`, no CSS-in-JS.
- next-intl i18n (English default, `/es/`); nav labels already come from `messages/`.
- This is Next.js 16+ App Router with breaking changes from older versions; consult `node_modules/next/dist/docs/` before writing framework code.
- No emoji (Unicode marks ok). No em dashes in user-facing copy.

## Architecture: single source of truth in `globals.css`

All sizing/spacing/type flows from `@theme` tokens. Components consume generated utilities (`text-hero`, `px-section`) instead of arbitrary values.

### New type scale tokens (`--text-*`, with paired `--text-*--line-height`)

| Token | Approx / fluid value | Replaces |
|-------|----------------------|----------|
| `--text-eyebrow` | ~11px | `text-[11px]` mono labels |
| `--text-micro` | ~11.5px | `text-[11.5px]` |
| `--text-small` | ~13px | `text-[13px]` |
| `--text-body` | ~13.5px | `text-[13.5px]` card body |
| `--text-body-lg` | clamp(14px, ..., 15px) | `text-[15px]` |
| `--text-lead` | clamp(15px, ..., 17px) | `text-[17px]` hero/section intro |
| `--text-card-title` | ~18px | `text-lg` card titles |
| `--text-card-title-lg` | ~20px | `text-xl` side-card titles |
| `--text-feature` | clamp(22px, ..., 26px) | `text-[26px]` CLI title |
| `--text-section` | clamp(28px, ..., 44px) | `text-4xl` / `text-[44px]` h2 |
| `--text-hero` | clamp(32px, ..., 64px) | hero h1 |
| `--text-hero-sm` | clamp(30px, ..., 52px) | quickstart h1 |

### New fluid section padding tokens

- `--p-pad-section-x: clamp(20px, 5vw, 56px)` (replaces fixed `--p-pad-xl` horizontal padding on sections/header/footer)
- `--p-pad-section-y: clamp(40px, 6vw, 80px)` (section vertical rhythm)

Existing `--p-pad-*` radii/spacing tokens are retained for component-internal padding.

### Centralized terminal tokens (stay dark)

- `--term-bg` (#0e1230), `--term-header` (#161c44), `--term-border` (#1c2452), `--term-title` (#8d96bd), `--term-text` (#c5cce8)
- Traffic-light dots: `--term-dot-red` (#ff5f57), `--term-dot-yellow` (#febc2e), `--term-dot-green` (#28c840)

These are defined once and consumed by `ui/terminal.tsx`. The per-line hex colors passed as terminal data in `home-page.tsx` remain (fixed-dark block data).

## Component changes

### Extract shared layout (removes duplication)

- New `src/components/site-header.tsx` (client component): logo, nav links, theme toggle, GitHub link, and the hamburger drawer. Replaces the duplicated inline `<header>` in both pages. Nav labels via `useTranslations`.
- New `src/components/site-footer.tsx`: shared footer, replaces the duplicated inline `<footer>` in both pages.
- Export both from `src/components/index.ts`.

### Hamburger drawer behavior

- Below `md`: nav links collapse behind a hamburger button. Theme toggle + GitHub stay visible at all widths.
- Button has `aria-label`, `aria-expanded`, `aria-controls`; drawer panel has matching `id`.
- Drawer opens below the header (stacked panel, full-width), uses existing color tokens and borders.
- Closes on link tap and on `Escape`. Open state via `useState`.
- At/above `md`: existing horizontal nav, unchanged.

### Responsive grids (mobile-first)

- Why section: `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3` (keep `gap-px` hairline + rounded container; verify rounded corners survive collapse).
- How section: `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`.
- Toolkit: `grid-cols-1 lg:grid-cols-[3fr_2fr]`; side-card inner grid stacks on mobile.
- Section header rows currently `flex justify-between items-end/baseline`: change to `flex-col gap-4 md:flex-row md:items-end md:justify-between` so the "All projects" button and eyebrow/heading do not collide on mobile.

### `ui/btn.tsx`

Unify size scale to consistent padding + type tokens, removing the mixed `text-[13px]` / `text-sm` / `text-[15px]`:
- `sm`: `px-4 py-2 text-small`
- `md`: `px-5 py-2.5 text-body-lg`
- `lg`: `px-6 py-3 text-body-lg` (slightly tightened from `px-7 py-3.5` for mobile reach; acceptable under "minor polish")

### `ui/card.tsx`

Responsive padding: default `p-5 sm:p-6`. Pages currently override with `!p-6` / `!p-5`; reconcile so overrides are consistent or removed in favor of the responsive default.

### `ui/terminal.tsx`

- Replace hardcoded hex with `--term-*` tokens (via arbitrary value referencing the var, e.g. `bg-[var(--term-bg)]`).
- Add `overflow-x-auto` to the content area so long command lines scroll horizontally instead of breaking the layout.
- Mono font size responsive: smaller on mobile, `text-small` from `sm` up (e.g. `text-[11px] sm:text-small`).

### `ui/tag.tsx`

Minor: use `text-eyebrow` token; keep `rounded-full` and the `color-mix` tones.

### Hero (both pages)

- `min-h-[85vh]` -> `min-h-[88svh] md:min-h-[85vh]` (use `svh` so mobile browser chrome does not clip).
- Apply `text-hero` / `text-hero-sm` and `text-lead` tokens.
- Section/hero horizontal padding -> `px-[var(--p-pad-section-x)]`, vertical -> token-driven.

### Page wiring (`home-page.tsx`, `quickstart-page.tsx`)

- Replace inline header/footer with `<SiteHeader />` / `<SiteFooter />`.
- Replace `px-[var(--p-pad-xl)] py-[var(--p-pad-xl)]` section padding with the new section tokens.
- Replace all arbitrary `text-[..px]` with the new type utilities.
- Apply responsive grid classes.

## Execution plan (subagents)

Dispatched along non-overlapping file boundaries after the plan is written:

1. **Tokens (lands first, others depend on it):** `globals.css` — type scale, section padding, terminal tokens.
2. **Shared chrome:** create `site-header.tsx` (hamburger drawer) + `site-footer.tsx`, update `index.ts`.
3. **UI components:** `ui/btn.tsx`, `ui/card.tsx`, `ui/terminal.tsx`, `ui/tag.tsx`.
4. **Page wiring:** `home-page.tsx`, `quickstart-page.tsx` consume new tokens, grids, and shared chrome.

Steps 2-4 depend on step 1 tokens existing. Steps 2 and 3 are independent of each other; step 4 depends on 2 and 3.

## Verification

- `pnpm build` succeeds, `pnpm lint` clean.
- Grep confirms no stray arbitrary `text-[..px]` or `px-[var(--p-pad-xl)]` remain in `home-page.tsx` / `quickstart-page.tsx`.
- User reviews in browser across mobile / tablet / desktop widths.

## Out of scope

- No new content or sections.
- No changes to `dither-map`, `rhumb-backdrop`, three.js canvases beyond ensuring they do not overflow.
- No unrelated refactoring.
