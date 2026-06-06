# Mobile-First Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Portolan website mobile-first by adding a single source of truth for type and section spacing in `globals.css`, extracting a shared hamburger-drawer header and footer, and wiring both pages and all `ui/` components to the new tokens with responsive grids.

**Architecture:** All sizing/spacing/type flows from `@theme`/`:root` tokens in `globals.css`. Tailwind v4 `--text-*` tokens auto-generate `text-*` utilities. Components consume utilities (`text-hero`, `px-[var(--p-pad-section-x)]`) instead of arbitrary values. The header and footer are extracted into shared components used by both pages.

**Tech Stack:** Next.js 16 App Router, React 19, Tailwind CSS v4 (pure utilities, no `@apply`), next-intl, pnpm. No test runner exists; verification is `pnpm build`, `pnpm lint`, and grep assertions.

---

## Notes for the implementer

- This is **Next.js 16+** with breaking changes. If you touch framework APIs, consult `node_modules/next/dist/docs/`. This plan only touches components/CSS, not routing or config, so no framework API changes are needed.
- **No `@apply`**, no CSS-in-JS, no new hex except in fixed-dark terminal blocks (which now read from tokens). Fonts stay Archivo + JetBrains Mono.
- No em dashes in user-facing copy (there is none added here).
- Run all commands from the repo root: `/Users/yharby/Documents/gh/portolan-sdi/portolan`.
- Order matters: **Task 1 (tokens) must land first** because every later task references the new utilities/vars.

## File Structure

- `src/app/globals.css` — MODIFY. Add type-scale tokens (`@theme inline`), fluid section-padding tokens and terminal tokens (`:root`).
- `src/components/site-header.tsx` — CREATE. Shared client header with hamburger drawer.
- `src/components/site-footer.tsx` — CREATE. Shared footer.
- `src/components/index.ts` — MODIFY. Export the two new components.
- `src/components/ui/btn.tsx` — MODIFY. Unify size scale to type tokens.
- `src/components/ui/card.tsx` — MODIFY. Responsive default padding.
- `src/components/ui/terminal.tsx` — MODIFY. Token colors + horizontal scroll.
- `src/components/ui/tag.tsx` — MODIFY. Use `text-eyebrow`.
- `src/components/home-page.tsx` — MODIFY. Use shared header/footer, section tokens, responsive grids, type tokens.
- `src/components/quickstart-page.tsx` — MODIFY. Same treatment.

---

## Task 1: Design tokens in globals.css

**Files:**
- Modify: `src/app/globals.css`

- [ ] **Step 1: Add type-scale tokens inside the `@theme inline` block**

In `src/app/globals.css`, find the line `--shadow-lg: var(--p-shadow-lg);` (inside `@theme inline`, currently line 106) and add the following immediately after it, before the closing `}` of `@theme inline`:

```css

  /* Type scale (auto-generates text-* utilities) */
  --text-eyebrow: 11px;
  --text-eyebrow--line-height: 1.4;
  --text-micro: 11.5px;
  --text-micro--line-height: 1.5;
  --text-small: 13px;
  --text-small--line-height: 1.5;
  --text-body: 13.5px;
  --text-body--line-height: 1.6;
  --text-body-lg: clamp(14px, 0.4vw + 13px, 15px);
  --text-body-lg--line-height: 1.6;
  --text-lead: clamp(15px, 0.6vw + 13.5px, 17px);
  --text-lead--line-height: 1.6;
  --text-card-title: 18px;
  --text-card-title--line-height: 1.3;
  --text-card-title-lg: 20px;
  --text-card-title-lg--line-height: 1.3;
  --text-feature: clamp(22px, 2.2vw + 14px, 26px);
  --text-feature--line-height: 1.2;
  --text-section-sm: clamp(24px, 1.5vw + 18px, 30px);
  --text-section-sm--line-height: 1.15;
  --text-section: clamp(28px, 4vw + 8px, 44px);
  --text-section--line-height: 1.1;
  --text-hero: clamp(32px, 5vw + 10px, 64px);
  --text-hero--line-height: 1.1;
  --text-hero-sm: clamp(30px, 4vw + 10px, 52px);
  --text-hero-sm--line-height: 1.1;
```

- [ ] **Step 2: Add fluid section-padding and terminal tokens inside `:root`**

In `src/app/globals.css`, find the `:root` Shadows block ending with the `--p-shadow-lg: ...;` declaration (currently lines 50-51) and add the following immediately after it, before the closing `}` of `:root`:

```css

  /* Fluid section padding (mobile-first) */
  --p-pad-section-x: clamp(20px, 5vw, 56px);
  --p-pad-section-y: clamp(40px, 6vw, 80px);

  /* Terminal (fixed-dark block, centralized) */
  --term-bg: #0e1230;
  --term-header: #161c44;
  --term-border: #1c2452;
  --term-title: #8d96bd;
  --term-text: #c5cce8;
  --term-dot-red: #ff5f57;
  --term-dot-yellow: #febc2e;
  --term-dot-green: #28c840;
```

- [ ] **Step 3: Verify the build compiles the new tokens**

Run: `pnpm build`
Expected: build succeeds (exit 0). The new `text-*` utilities are now available.

- [ ] **Step 4: Commit**

```bash
git add src/app/globals.css
git commit -m "Add type scale, section padding, and terminal tokens"
```

---

## Task 2: Shared SiteHeader with hamburger drawer

**Files:**
- Create: `src/components/site-header.tsx`

- [ ] **Step 1: Create `src/components/site-header.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { PortolanLogo } from "./portolan-logo";
import { ThemeToggle } from "./theme-toggle";

const navLinks = [
  { href: "/#why", key: "why" },
  { href: "/#how", key: "howItWorks" },
  { href: "/#tools", key: "tools" },
  {
    href: "https://portolan-sdi.github.io/portolan-cli",
    key: "docs",
    external: true,
  },
] as const;

export function SiteHeader() {
  const t = useTranslations();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <header className="relative border-b border-p-line-soft">
      <div className="flex items-center justify-between px-[var(--p-pad-section-x)] py-4">
        <a href="/" aria-label="Portolan home">
          <PortolanLogo size={28} />
        </a>
        <nav className="hidden md:flex gap-7 text-small text-p-ink-2">
          {navLinks.map((link) => (
            <a
              key={link.key}
              href={link.href}
              className="text-inherit hover:text-p-ink transition-colors"
            >
              {t(`nav.${link.key}`)}
              {"external" in link && link.external ? " ↗" : ""}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <a
            href="https://github.com/portolan-sdi"
            aria-label="GitHub"
            className="inline-flex items-center justify-center w-8 h-8 rounded-[var(--p-r-md)] text-p-ink-2 transition-colors hover:bg-p-bg-soft hover:text-p-ink"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.36-3.87-1.36-.52-1.33-1.28-1.69-1.28-1.69-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11.07 11.07 0 015.79 0c2.21-1.49 3.18-1.18 3.18-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.42-2.69 5.39-5.25 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56C20.21 21.39 23.5 17.08 23.5 12 23.5 5.65 18.35.5 12 .5z" />
            </svg>
          </a>
          <button
            type="button"
            aria-label="Toggle menu"
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((v) => !v)}
            className="md:hidden inline-flex items-center justify-center w-8 h-8 rounded-[var(--p-r-md)] text-p-ink-2 transition-colors hover:bg-p-bg-soft hover:text-p-ink"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              {open ? (
                <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
              ) : (
                <path d="M3 6h18M3 12h18M3 18h18" strokeLinecap="round" />
              )}
            </svg>
          </button>
        </div>
      </div>
      {open && (
        <nav
          id="mobile-nav"
          className="md:hidden flex flex-col px-[var(--p-pad-section-x)] pb-4 gap-1 border-t border-p-line-soft bg-p-bg"
        >
          {navLinks.map((link) => (
            <a
              key={link.key}
              href={link.href}
              onClick={() => setOpen(false)}
              className="py-2.5 text-body-lg text-p-ink-2 hover:text-p-ink transition-colors"
            >
              {t(`nav.${link.key}`)}
              {"external" in link && link.external ? " ↗" : ""}
            </a>
          ))}
        </nav>
      )}
    </header>
  );
}
```

- [ ] **Step 2: Verify it typechecks via build**

Run: `pnpm build`
Expected: build succeeds. (The component is not yet imported anywhere; this only checks it compiles.)

- [ ] **Step 3: Commit**

```bash
git add src/components/site-header.tsx
git commit -m "Add shared SiteHeader with hamburger drawer"
```

---

## Task 3: Shared SiteFooter

**Files:**
- Create: `src/components/site-footer.tsx`

- [ ] **Step 1: Create `src/components/site-footer.tsx`**

```tsx
import { useTranslations } from "next-intl";
import { PortolanLogo } from "./portolan-logo";

export function SiteFooter() {
  const t = useTranslations();
  return (
    <footer className="px-[var(--p-pad-section-x)] py-[var(--p-pad-lg)] border-t border-p-line-soft flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 text-small text-p-ink-3">
      <PortolanLogo size={22} />
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <span>{t("footer.openGovernance")}</span>
        <span>{t("footer.license")}</span>
        <span>{t("footer.repo")}</span>
      </div>
    </footer>
  );
}
```

- [ ] **Step 2: Export both new components from `src/components/index.ts`**

In `src/components/index.ts`, add these two lines after the existing `export { ThemeToggle } from "./theme-toggle";` line:

```ts
export { SiteHeader } from "./site-header";
export { SiteFooter } from "./site-footer";
```

- [ ] **Step 3: Verify build**

Run: `pnpm build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add src/components/site-footer.tsx src/components/index.ts
git commit -m "Add shared SiteFooter and export new layout components"
```

---

## Task 4: Update ui/btn.tsx size scale

**Files:**
- Modify: `src/components/ui/btn.tsx:12-16`

- [ ] **Step 1: Replace the `sizeClasses` record**

Replace this block:

```tsx
const sizeClasses: Record<BtnSize, string> = {
  sm: "px-4 py-2 text-[13px]",
  md: "px-5 py-2.5 text-sm",
  lg: "px-7 py-3.5 text-[15px]",
};
```

with:

```tsx
const sizeClasses: Record<BtnSize, string> = {
  sm: "px-4 py-2 text-small",
  md: "px-5 py-2.5 text-body-lg",
  lg: "px-6 py-3 text-body-lg",
};
```

- [ ] **Step 2: Verify build**

Run: `pnpm build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add src/components/ui/btn.tsx
git commit -m "Unify Btn size scale to type tokens"
```

---

## Task 5: Update ui/card.tsx responsive padding

**Files:**
- Modify: `src/components/ui/card.tsx:10-15`

- [ ] **Step 1: Replace the default padding in the className**

Replace this string inside the className template literal:

```tsx
        bg-p-paper border border-p-line
        rounded-[var(--p-r-lg)] p-[var(--p-pad-md)]
        shadow-[var(--p-shadow-sm)] relative
```

with:

```tsx
        bg-p-paper border border-p-line
        rounded-[var(--p-r-lg)] p-5 sm:p-6
        shadow-[var(--p-shadow-sm)] relative
```

- [ ] **Step 2: Verify build**

Run: `pnpm build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add src/components/ui/card.tsx
git commit -m "Make Card padding responsive"
```

---

## Task 6: Update ui/terminal.tsx to use tokens and scroll

**Files:**
- Modify: `src/components/ui/terminal.tsx:11-33`

- [ ] **Step 1: Replace the component body**

Replace the entire `Terminal` function (lines 11-33) with:

```tsx
export function Terminal({ lines = [], title = "portolan" }: TerminalProps) {
  return (
    <div className="bg-[var(--term-bg)] rounded-[var(--p-r-lg)] border border-[var(--term-border)] shadow-[var(--p-shadow-md)] overflow-hidden font-mono text-[11px] sm:text-small">
      <div className="bg-[var(--term-header)] px-4 py-2.5 flex items-center gap-2 border-b border-[var(--term-border)]">
        <span className="w-2.5 h-2.5 rounded-full bg-[var(--term-dot-red)]" />
        <span className="w-2.5 h-2.5 rounded-full bg-[var(--term-dot-yellow)]" />
        <span className="w-2.5 h-2.5 rounded-full bg-[var(--term-dot-green)]" />
        <span className="ml-3 text-[var(--term-title)] text-xs">{title}</span>
      </div>
      <div className="px-4 py-4 text-[var(--term-text)] leading-relaxed overflow-x-auto">
        {lines.map((line, i) => {
          if (typeof line === "string") {
            return (
              <div key={i} className="whitespace-pre">
                {line}
              </div>
            );
          }
          return (
            <div
              key={i}
              className="whitespace-pre"
              style={{ color: line.color || "var(--term-text)" }}
            >
              {line.text}
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `pnpm build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add src/components/ui/terminal.tsx
git commit -m "Tokenize Terminal colors and add horizontal scroll"
```

---

## Task 7: Update ui/tag.tsx type token

**Files:**
- Modify: `src/components/ui/tag.tsx:25-32`

- [ ] **Step 1: Replace `text-xs` with `text-eyebrow`**

In the className template literal, replace:

```tsx
        inline-flex items-center gap-2
        text-xs font-mono
```

with:

```tsx
        inline-flex items-center gap-2
        text-eyebrow font-mono
```

- [ ] **Step 2: Verify build**

Run: `pnpm build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add src/components/ui/tag.tsx
git commit -m "Use eyebrow type token in Tag"
```

---

## Task 8: Wire home-page.tsx to shared chrome, tokens, and responsive grids

**Files:**
- Modify: `src/components/home-page.tsx`

- [ ] **Step 1: Update imports (lines 4-8)**

Replace:

```tsx
import { PortolanLogo } from "./portolan-logo";
import { RhumbBackdrop } from "./rhumb-backdrop";
import { DitherMap } from "./dither-map";
import { ThemeToggle } from "./theme-toggle";
import { Btn, Tag, Card, Terminal } from "./ui";
```

with:

```tsx
import { RhumbBackdrop } from "./rhumb-backdrop";
import { DitherMap } from "./dither-map";
import { SiteHeader } from "./site-header";
import { SiteFooter } from "./site-footer";
import { Btn, Tag, Card, Terminal } from "./ui";
```

- [ ] **Step 2: Replace the inline `<header>` (lines 50-84) with `<SiteHeader />`**

Replace the entire block from `{/* Header */}` through the closing `</header>` with:

```tsx
      {/* Header */}
      <SiteHeader />
```

- [ ] **Step 3: Update the Hero section opening tags**

Replace:

```tsx
      <section className="relative min-h-[85vh] flex items-center border-b border-p-line-soft overflow-hidden">
        <DitherMap className="absolute inset-0 w-full h-full opacity-80 dark:opacity-60" />
        <div className="absolute inset-0 bg-gradient-to-r from-p-bg via-p-bg/85 via-50% to-p-bg/40" />
        <div className="relative z-10 px-[var(--p-pad-xl)] py-[var(--p-pad-xl)] w-full">
```

with:

```tsx
      <section className="relative min-h-[88svh] md:min-h-[85vh] flex items-center border-b border-p-line-soft overflow-hidden">
        <DitherMap className="absolute inset-0 w-full h-full opacity-80 dark:opacity-60" />
        <div className="absolute inset-0 bg-gradient-to-r from-p-bg via-p-bg/85 via-50% to-p-bg/40" />
        <div className="relative z-10 px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] w-full">
```

- [ ] **Step 4: Update Hero h1 and paragraph**

Replace:

```tsx
              <h1 className="text-[clamp(40px,5vw,64px)] leading-[1.1] font-semibold tracking-[-0.03em] mb-6">
                {t("hero.title")} <br />
                <span className="bg-gradient-to-r from-p-grad-a to-p-grad-b bg-clip-text text-transparent">
                  {t("hero.titleHighlight")}
                </span>
              </h1>
              <p className="text-[17px] leading-relaxed mb-10">
                {t("hero.description")}
              </p>
```

with:

```tsx
              <h1 className="text-hero font-semibold tracking-[-0.03em] mb-6">
                {t("hero.title")} <br />
                <span className="bg-gradient-to-r from-p-grad-a to-p-grad-b bg-clip-text text-transparent">
                  {t("hero.titleHighlight")}
                </span>
              </h1>
              <p className="text-lead leading-relaxed mb-10">
                {t("hero.description")}
              </p>
```

- [ ] **Step 5: Update the Why section (heading, padding, grid, cards)**

Replace the Why `<section>` open tag:

```tsx
      <section id="why" className="px-[var(--p-pad-xl)] py-[var(--p-pad-xl)]">
```

with:

```tsx
      <section id="why" className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)]">
```

Replace the eyebrow + h2:

```tsx
              <span className="font-mono text-[11px] text-p-ink-3 tracking-[0.08em]">
                {t("why.eyebrow")}
              </span>
              <h2 className="text-4xl mt-1.5 font-semibold tracking-[-0.02em]">
                {t("why.title")}
              </h2>
```

with:

```tsx
              <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
                {t("why.eyebrow")}
              </span>
              <h2 className="text-section mt-1.5 font-semibold tracking-[-0.02em]">
                {t("why.title")}
              </h2>
```

Replace the grid container:

```tsx
          <div className="grid grid-cols-3 gap-px bg-p-line border border-p-line rounded-[var(--p-r-lg)] overflow-hidden">
```

with:

```tsx
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-px bg-p-line border border-p-line rounded-[var(--p-r-lg)] overflow-hidden">
```

Replace the card internals:

```tsx
                  <span className="font-mono text-[11px] text-p-ink-3">{card.id}</span>
                  <span className="w-2 h-2 rounded-full bg-p-primary" />
                </div>
                <h3 className="text-lg font-semibold">
                  {t(`why.cards.${card.key}.title`)}
                </h3>
                <p className="text-[13.5px] leading-relaxed">
                  {t(`why.cards.${card.key}.description`)}
                </p>
                <div className="mt-auto font-mono text-[11.5px] text-p-primary-ink px-2.5 py-1.5 bg-p-bg-soft rounded-[var(--p-r-sm)] border border-p-line-soft self-start">
```

with:

```tsx
                  <span className="font-mono text-eyebrow text-p-ink-3">{card.id}</span>
                  <span className="w-2 h-2 rounded-full bg-p-primary" />
                </div>
                <h3 className="text-card-title font-semibold">
                  {t(`why.cards.${card.key}.title`)}
                </h3>
                <p className="text-body leading-relaxed">
                  {t(`why.cards.${card.key}.description`)}
                </p>
                <div className="mt-auto font-mono text-micro text-p-primary-ink px-2.5 py-1.5 bg-p-bg-soft rounded-[var(--p-r-sm)] border border-p-line-soft self-start">
```

- [ ] **Step 6: Update the How section (padding, heading, subtitle, grid, cards)**

Replace the How `<section>` open tag:

```tsx
      <section id="how" className="px-[var(--p-pad-xl)] py-[var(--p-pad-xl)] bg-p-bg-soft border-y border-p-line-soft">
```

with:

```tsx
      <section id="how" className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] bg-p-bg-soft border-y border-p-line-soft">
```

Replace the eyebrow + h2 + subtitle:

```tsx
          <span className="font-mono text-[11px] text-p-ink-3 tracking-[0.08em]">
            {t("howItWorks.eyebrow")}
          </span>
          <h2 className="text-4xl mt-1.5 mb-3 font-semibold tracking-[-0.02em]">
            {t("howItWorks.title")}
          </h2>
          <p className="text-[15px] leading-relaxed max-w-[720px] mb-10">
            {t("howItWorks.subtitle")}
          </p>
          <div className="grid grid-cols-4 gap-5">
            {howSteps.map((step) => (
              <Card key={step} className="!p-6 flex flex-col gap-3">
                <div className="flex justify-between items-center">
                  <span className="font-mono text-[11px] text-p-ink-3">
                    {t(`howItWorks.steps.${step}.id`)}
                  </span>
                  <span className="w-2 h-2 rounded-full bg-p-accent" />
                </div>
                <h3 className="text-lg font-semibold">
                  {t(`howItWorks.steps.${step}.title`)}
                </h3>
                <p className="text-[13.5px] leading-relaxed">
                  {t(`howItWorks.steps.${step}.description`)}
                </p>
              </Card>
            ))}
          </div>
```

with:

```tsx
          <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
            {t("howItWorks.eyebrow")}
          </span>
          <h2 className="text-section mt-1.5 mb-3 font-semibold tracking-[-0.02em]">
            {t("howItWorks.title")}
          </h2>
          <p className="text-body-lg leading-relaxed max-w-[720px] mb-10">
            {t("howItWorks.subtitle")}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {howSteps.map((step) => (
              <Card key={step} className="flex flex-col gap-3">
                <div className="flex justify-between items-center">
                  <span className="font-mono text-eyebrow text-p-ink-3">
                    {t(`howItWorks.steps.${step}.id`)}
                  </span>
                  <span className="w-2 h-2 rounded-full bg-p-accent" />
                </div>
                <h3 className="text-card-title font-semibold">
                  {t(`howItWorks.steps.${step}.title`)}
                </h3>
                <p className="text-body leading-relaxed">
                  {t(`howItWorks.steps.${step}.description`)}
                </p>
              </Card>
            ))}
          </div>
```

- [ ] **Step 7: Update the Toolkit section (padding, header row, heading, grid)**

Replace the Toolkit `<section>` open tag:

```tsx
      <section
        id="tools"
        className="px-[var(--p-pad-xl)] py-[calc(var(--p-pad-xl)*1.4)] relative overflow-hidden"
      >
```

with:

```tsx
      <section
        id="tools"
        className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] relative overflow-hidden"
      >
```

Replace the header row + eyebrow + h2:

```tsx
          <div className="flex justify-between items-end mb-10">
            <div>
              <span className="font-mono text-[11px] text-p-ink-3 tracking-[0.08em]">
                {t("toolkit.eyebrow")}
              </span>
              <h2 className="text-[44px] mt-1.5 font-semibold leading-tight max-w-[720px] tracking-[-0.02em]">
                {t("toolkit.title")}
              </h2>
            </div>
```

with:

```tsx
          <div className="flex flex-col gap-4 md:flex-row md:justify-between md:items-end mb-10">
            <div>
              <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
                {t("toolkit.eyebrow")}
              </span>
              <h2 className="text-section mt-1.5 font-semibold leading-tight max-w-[720px] tracking-[-0.02em]">
                {t("toolkit.title")}
              </h2>
            </div>
```

Replace the toolkit grid container:

```tsx
          <div className="grid grid-cols-[3fr_2fr] gap-5 items-stretch">
```

with:

```tsx
          <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-5 items-stretch">
```

- [ ] **Step 8: Update the CLI card and side cards type/padding**

Replace the CLI card block:

```tsx
              <Card className="!p-6 flex flex-col gap-4 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-mono text-xs text-p-primary-ink mb-1">
                      {t("toolkit.cli.name")}
                    </div>
                    <h3 className="text-[26px]">{t("toolkit.cli.title")}</h3>
                  </div>
                  <Tag tone="accent">{t("toolkit.cli.version")}</Tag>
                </div>
                <p className="text-sm leading-relaxed">{t("toolkit.cli.description")}</p>
                <Terminal title="my-catalog · zsh" lines={terminalLines} />
                <div className="font-mono text-[11.5px] text-p-ink-3 mt-auto">
                  {t("toolkit.cli.compatibility")}
                </div>
              </Card>
```

with:

```tsx
              <Card className="flex flex-col gap-4 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-mono text-xs text-p-primary-ink mb-1">
                      {t("toolkit.cli.name")}
                    </div>
                    <h3 className="text-feature">{t("toolkit.cli.title")}</h3>
                  </div>
                  <Tag tone="accent">{t("toolkit.cli.version")}</Tag>
                </div>
                <p className="text-body-lg leading-relaxed">{t("toolkit.cli.description")}</p>
                <Terminal title="my-catalog · zsh" lines={terminalLines} />
                <div className="font-mono text-micro text-p-ink-3 mt-auto">
                  {t("toolkit.cli.compatibility")}
                </div>
              </Card>
```

Replace the viewer side card:

```tsx
                <Card className="!p-5 flex flex-col gap-3 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                  <div className="flex justify-between items-start">
                    <div className="font-mono text-xs text-p-primary-ink">
                      {t("toolkit.viewer.name")}
                    </div>
                    <Tag tone="default">{t("toolkit.viewer.tag")}</Tag>
                  </div>
                  <h3 className="text-xl">{t("toolkit.viewer.title")}</h3>
                  <p className="text-[13.5px] leading-relaxed">
                    {t("toolkit.viewer.description")}
                  </p>
                  <span className="mt-auto text-[13px] text-p-primary hover:underline">
                    {t("toolkit.readMore")} →
                  </span>
                </Card>
```

with:

```tsx
                <Card className="flex flex-col gap-3 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                  <div className="flex justify-between items-start">
                    <div className="font-mono text-xs text-p-primary-ink">
                      {t("toolkit.viewer.name")}
                    </div>
                    <Tag tone="default">{t("toolkit.viewer.tag")}</Tag>
                  </div>
                  <h3 className="text-card-title-lg">{t("toolkit.viewer.title")}</h3>
                  <p className="text-body leading-relaxed">
                    {t("toolkit.viewer.description")}
                  </p>
                  <span className="mt-auto text-small text-p-primary hover:underline">
                    {t("toolkit.readMore")} →
                  </span>
                </Card>
```

Replace the skills side card:

```tsx
                <Card className="!p-5 flex flex-col gap-3 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                  <div className="flex justify-between items-start">
                    <div className="font-mono text-xs text-p-primary-ink">
                      {t("toolkit.skills.name")}
                    </div>
                    <Tag tone="default">{t("toolkit.skills.tag")}</Tag>
                  </div>
                  <h3 className="text-xl">{t("toolkit.skills.title")}</h3>
                  <p className="text-[13.5px] leading-relaxed">
                    {t("toolkit.skills.description")}
                  </p>
                  <span className="mt-auto text-[13px] text-p-primary hover:underline">
                    {t("toolkit.readMore")} →
                  </span>
                </Card>
```

with:

```tsx
                <Card className="flex flex-col gap-3 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                  <div className="flex justify-between items-start">
                    <div className="font-mono text-xs text-p-primary-ink">
                      {t("toolkit.skills.name")}
                    </div>
                    <Tag tone="default">{t("toolkit.skills.tag")}</Tag>
                  </div>
                  <h3 className="text-card-title-lg">{t("toolkit.skills.title")}</h3>
                  <p className="text-body leading-relaxed">
                    {t("toolkit.skills.description")}
                  </p>
                  <span className="mt-auto text-small text-p-primary hover:underline">
                    {t("toolkit.readMore")} →
                  </span>
                </Card>
```

- [ ] **Step 9: Replace the inline `<footer>` (lines 277-285) with `<SiteFooter />`**

Replace the entire block from `{/* Footer */}` through the closing `</footer>` with:

```tsx
      {/* Footer */}
      <SiteFooter />
```

- [ ] **Step 10: Verify build and lint**

Run: `pnpm build && pnpm lint`
Expected: both succeed. No "unused import" lint errors (PortolanLogo and ThemeToggle imports were removed in Step 1).

- [ ] **Step 11: Commit**

```bash
git add src/components/home-page.tsx
git commit -m "Make home page mobile-first with shared chrome and tokens"
```

---

## Task 9: Wire quickstart-page.tsx to shared chrome, tokens

**Files:**
- Modify: `src/components/quickstart-page.tsx`

- [ ] **Step 1: Update imports (lines 4-6)**

Replace:

```tsx
import { PortolanLogo } from "./portolan-logo";
import { ThemeToggle } from "./theme-toggle";
import { Btn, Card, Terminal } from "./ui";
```

with:

```tsx
import { SiteHeader } from "./site-header";
import { SiteFooter } from "./site-footer";
import { Btn, Card, Terminal } from "./ui";
```

- [ ] **Step 2: Replace the inline `<header>` (lines 60-94) with `<SiteHeader />`**

Replace the entire block from `{/* Header */}` through the closing `</header>` with:

```tsx
      {/* Header */}
      <SiteHeader />
```

- [ ] **Step 3: Update the Hero section**

Replace:

```tsx
      <section className="px-[var(--p-pad-xl)] pt-[var(--p-pad-xl)] pb-[var(--p-pad-lg)]">
        <div className="max-w-[860px] mx-auto">
          <h1 className="text-[clamp(36px,4vw,52px)] leading-[1.1] font-semibold tracking-[-0.03em] mb-4">
            {t("quickstart.title")}
          </h1>
          <p className="text-[17px] leading-relaxed text-p-ink-2">
            {t("quickstart.intro")}
          </p>
        </div>
      </section>
```

with:

```tsx
      <section className="px-[var(--p-pad-section-x)] pt-[var(--p-pad-section-y)] pb-[var(--p-pad-lg)]">
        <div className="max-w-[860px] mx-auto">
          <h1 className="text-hero-sm font-semibold tracking-[-0.03em] mb-4">
            {t("quickstart.title")}
          </h1>
          <p className="text-lead leading-relaxed text-p-ink-2">
            {t("quickstart.intro")}
          </p>
        </div>
      </section>
```

- [ ] **Step 4: Update the Browse section**

Replace:

```tsx
      <section className="px-[var(--p-pad-xl)] py-[var(--p-pad-lg)]">
        <div className="max-w-[860px] mx-auto">
          <span className="font-mono text-[11px] text-p-ink-3 tracking-[0.08em]">
            {t("quickstart.browse.eyebrow")}
          </span>
          <h2 className="text-3xl mt-1.5 mb-4 font-semibold tracking-[-0.02em]">
            {t("quickstart.browse.title")}
          </h2>
          <p className="text-[15px] leading-relaxed mb-6">
            {t("quickstart.browse.description")}
          </p>
```

with:

```tsx
      <section className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)]">
        <div className="max-w-[860px] mx-auto">
          <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
            {t("quickstart.browse.eyebrow")}
          </span>
          <h2 className="text-section-sm mt-1.5 mb-4 font-semibold tracking-[-0.02em]">
            {t("quickstart.browse.title")}
          </h2>
          <p className="text-body-lg leading-relaxed mb-6">
            {t("quickstart.browse.description")}
          </p>
```

Then replace the duckdb Card block:

```tsx
          <Card className="!p-6">
            <h3 className="text-lg font-semibold mb-2">
              {t("quickstart.browse.duckdb.title")}
            </h3>
            <p className="text-[13.5px] leading-relaxed mb-4">
              {t("quickstart.browse.duckdb.description")}
            </p>
            <Terminal title="duckdb" lines={duckdbLines} />
          </Card>
```

with:

```tsx
          <Card>
            <h3 className="text-card-title font-semibold mb-2">
              {t("quickstart.browse.duckdb.title")}
            </h3>
            <p className="text-body leading-relaxed mb-4">
              {t("quickstart.browse.duckdb.description")}
            </p>
            <Terminal title="duckdb" lines={duckdbLines} />
          </Card>
```

- [ ] **Step 5: Update the Publish section header and both sub-paths**

Replace:

```tsx
      <section className="px-[var(--p-pad-xl)] py-[var(--p-pad-lg)] bg-p-bg-soft border-y border-p-line-soft">
        <div className="max-w-[860px] mx-auto">
          <span className="font-mono text-[11px] text-p-ink-3 tracking-[0.08em]">
            {t("quickstart.publish.eyebrow")}
          </span>
          <h2 className="text-3xl mt-1.5 mb-4 font-semibold tracking-[-0.02em]">
            {t("quickstart.publish.title")}
          </h2>
          <p className="text-[15px] leading-relaxed mb-10">
            {t("quickstart.publish.description")}
          </p>

          {/* CLI path */}
          <div className="mb-12">
            <h3 className="text-xl font-semibold mb-2">{t("quickstart.cli.title")}</h3>
            <p className="text-[14px] leading-relaxed mb-4">
              {t("quickstart.cli.description")}
            </p>
```

with:

```tsx
      <section className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] bg-p-bg-soft border-y border-p-line-soft">
        <div className="max-w-[860px] mx-auto">
          <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
            {t("quickstart.publish.eyebrow")}
          </span>
          <h2 className="text-section-sm mt-1.5 mb-4 font-semibold tracking-[-0.02em]">
            {t("quickstart.publish.title")}
          </h2>
          <p className="text-body-lg leading-relaxed mb-10">
            {t("quickstart.publish.description")}
          </p>

          {/* CLI path */}
          <div className="mb-12">
            <h3 className="text-card-title-lg font-semibold mb-2">{t("quickstart.cli.title")}</h3>
            <p className="text-body-lg leading-relaxed mb-4">
              {t("quickstart.cli.description")}
            </p>
```

Then replace the Claude sub-path heading + paragraph:

```tsx
            <h3 className="text-xl font-semibold mb-2">{t("quickstart.claude.title")}</h3>
            <p className="text-[14px] leading-relaxed mb-4">
              {t("quickstart.claude.description")}
            </p>
```

with:

```tsx
            <h3 className="text-card-title-lg font-semibold mb-2">{t("quickstart.claude.title")}</h3>
            <p className="text-body-lg leading-relaxed mb-4">
              {t("quickstart.claude.description")}
            </p>
```

- [ ] **Step 6: Update the What's next section**

Replace:

```tsx
      <section className="px-[var(--p-pad-xl)] py-[var(--p-pad-lg)]">
        <div className="max-w-[860px] mx-auto">
          <h2 className="text-2xl mb-6 font-semibold tracking-[-0.02em]">
            {t("quickstart.next.title")}
          </h2>
```

with:

```tsx
      <section className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)]">
        <div className="max-w-[860px] mx-auto">
          <h2 className="text-section-sm mb-6 font-semibold tracking-[-0.02em]">
            {t("quickstart.next.title")}
          </h2>
```

- [ ] **Step 7: Replace the inline `<footer>` (lines 198-206) with `<SiteFooter />`**

Replace the entire block from `{/* Footer */}` through the closing `</footer>` with:

```tsx
      {/* Footer */}
      <SiteFooter />
```

- [ ] **Step 8: Verify build and lint**

Run: `pnpm build && pnpm lint`
Expected: both succeed. No unused-import errors.

- [ ] **Step 9: Commit**

```bash
git add src/components/quickstart-page.tsx
git commit -m "Make quickstart page mobile-first with shared chrome and tokens"
```

---

## Task 10: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Confirm no stray fixed section padding remains in pages**

Run: `grep -rn "p-pad-xl" src/components/home-page.tsx src/components/quickstart-page.tsx`
Expected: no output (exit 1). All section padding now uses `--p-pad-section-x/y`.

- [ ] **Step 2: Confirm no arbitrary pixel font sizes remain in pages**

Run: `grep -rEn "text-\[[0-9]" src/components/home-page.tsx src/components/quickstart-page.tsx`
Expected: no output (exit 1). All font sizes use type tokens.

- [ ] **Step 3: Confirm terminal no longer hardcodes hex**

Run: `grep -rEn "#[0-9a-fA-F]{6}" src/components/ui/terminal.tsx`
Expected: no output (exit 1). Terminal colors come from `--term-*` tokens. (Per-line hex in page data files is allowed and out of scope.)

- [ ] **Step 4: Full build + lint**

Run: `pnpm build && pnpm lint`
Expected: both succeed with exit 0.

- [ ] **Step 5: Final commit (if any verification fixes were needed)**

```bash
git add -A
git commit -m "Mobile-first refactor verification fixes" || echo "nothing to commit"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** type scale (Task 1), section padding (Task 1), terminal tokens (Tasks 1, 6), shared header with hamburger drawer (Task 2), shared footer (Task 3), btn/card/terminal/tag (Tasks 4-7), responsive grids + page wiring (Tasks 8-9), verification (Task 10). All spec sections mapped. `--text-section-sm` was added beyond the spec table to preserve quickstart's smaller heading scale (noted in spec as quickstart h2 mapping; within the "unify type" scope).
- **Placeholder scan:** none.
- **Type/name consistency:** `SiteHeader`/`SiteFooter` names consistent across create, export, and both imports. Token names (`text-eyebrow`, `text-micro`, `text-small`, `text-body`, `text-body-lg`, `text-lead`, `text-card-title`, `text-card-title-lg`, `text-feature`, `text-section-sm`, `text-section`, `text-hero`, `text-hero-sm`) consistent between Task 1 definitions and all usages. `--p-pad-section-x/y` and `--term-*` consistent between definition and usage.
