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
- **Corners are round.** `--p-r-md` (10px) for buttons, `--p-r-lg` (16px) for cards.
- **Logo:** Two-pennant SVG in `PortolanLogo`. Always rendered with the gradient unless on dark surface.

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

## i18n

- Default locale: English (no URL prefix)
- Spanish: `/es/` prefix
- Translation files in `messages/` directory
- Use `useTranslations` hook in client components
