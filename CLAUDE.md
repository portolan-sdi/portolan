@AGENTS.md

# Portolan Website

## Identity

**Portolan** is a spatial data infrastructure (SDI) toolkit and set of conventions for publishing geospatial data as cloud-native files on object storage. It is **not** a hosting service — Portolan does not host data. It is open source, openly governed, and free.

Key framing words: **open · sovereign · AI-ready · cheap · cloud-native**.

Avoid framing Portolan as a SaaS, a portal, a product, or a company.

## Visual System (non-negotiable)

- **Type:** Archivo (sans, all text) + JetBrains Mono (code, labels, eyebrows). No other fonts in production.
- **Color tokens:** Use CSS variables from `globals.css`. Never hardcode hex except in SVG gradients and fixed-dark terminal/map blocks.
- **Primary palette:** `--p-primary: #4163cc`, `--p-grad-a: #395eca`, `--p-grad-b: #848bd8`, `--p-accent: #f4b860`
- **Type scale (single source of truth):** Use the named utilities generated from `--text-*` tokens in `globals.css`, never arbitrary sizes like `text-[13px]`. Available: `text-eyebrow`, `text-micro`, `text-small`, `text-body`, `text-body-lg`, `text-lead`, `text-card-title`, `text-card-title-lg`, `text-feature`, `text-section-sm`, `text-section`, `text-hero`, `text-hero-sm`. Headings and lead text are fluid via `clamp()`.
- **Corners are round.** `--p-r-md` (10px) for buttons, `--p-r-lg` (16px) for cards.
- **Terminal blocks** are intentionally fixed-dark and driven by the `--term-*` tokens. They do not follow the light/dark theme.
- **Logo:** Two-pennant SVG in `PortolanLogo`. Always rendered with the gradient unless on dark surface.

## Layout & Responsiveness

- **Mobile-first, always.** Start from the single-column small-screen layout, then add `sm:` / `md:` / `lg:` breakpoints. Never write a desktop-only layout.
- **Section padding:** sections use `px-[var(--p-pad-section-x)]` and `py-[var(--p-pad-section-y)]` (fluid `clamp()` tokens). Do not use the fixed `--p-pad-xl` for section padding.
- **Grids collapse:** multi-column grids start at `grid-cols-1` and step up (for example `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`).
- **Shared chrome:** the header and footer come from `SiteHeader` and `SiteFooter`. Do not inline `<header>` / `<footer>` markup in pages. The header carries the mobile hamburger drawer.

## Tech Stack

- Next.js 16+ App Router with TypeScript
- Tailwind CSS (pure utilities, no `@apply`)
- next-intl for i18n (English default, Spanish at `/es/`)
- pnpm for package management
- Deploying to Vercel at portolan-sdi.org

## What NOT to do

- Don't add a "mission" or "about" section to the homepage
- Don't reintroduce the install button in the header
- Don't add emoji (except Unicode marks: ↗, →, ·, //)
- Don't add icons to nav items
- Don't introduce CSS-in-JS libraries
- Don't add filler content
- Don't use arbitrary font-size values (`text-[13px]`); use the type scale
- Don't inline header/footer markup; use `SiteHeader` / `SiteFooter`

## i18n

- Default locale: English (no URL prefix)
- Spanish: `/es/` prefix
- Translation files in `messages/` directory
- Use `useTranslations` hook in client components
