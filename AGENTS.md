<!-- ops-sync:begin — synced from portolan-sdi/portolan-ops. Edit there, not here. -->
# Portolan agent norms

These rules apply to AI agents working in any portolan-sdi repo. Every downstream repo repeats this text verbatim as a synced block at the top of its own `AGENTS.md`. Repo-specific instructions live below the block and override the canonical rules in that repo only.

Claude Code does not read `AGENTS.md`. Each repo has a one-line `CLAUDE.md` that imports it instead. Put repo-specific instructions in `AGENTS.md`, never in `CLAUDE.md`, which the sync overwrites.

## Ground rules

The [portolan-spec](https://github.com/portolan-sdi/portolan-spec) repo is ground truth for the Portolan specification. The CLI, `rashid`, the registry, and every other tool implement the specification. They are downstream of it. Never describe the CLI as the source of truth. Propose spec changes in portolan-spec.

Before documenting any command, flag, or API, verify it exists in the released tool. A fabricated example persists beyond the session that wrote it.

Every repo uses Apache-2.0 except portolan-browser and portolan-nl-demo, which are ISC forks. See [norms/repos.md](https://github.com/portolan-sdi/portolan-ops/blob/main/norms/repos.md) for the record. Never introduce code under another license without a human decision recorded there.

Never bypass pre-commit hooks or CI gates. Green means green.

Write commits in conventional form. Squash-merge makes the pull request title become the commit message.

## Pull requests and issues

Write every issue and pull request in two layers. The human layer first states what is wrong or missing. It explains why the problem matters and what should happen instead. Someone who did not follow your investigation should understand it in about a minute. The agent layer then provides evidence and implementation detail. It also records constraints, edge cases, and verification.

There is no word limit. A 700-word issue is good when its first 150 words make the outcome obvious. A 150-word issue is bad when it compresses the meaning into prose the reader has to unpack. Optimize for fast comprehension, not for short tickets.

Write them in Simplified Technical English (ASD-STE100). The rules are an output style, `.claude/output-styles/simplified-technical-english.md`, which every repo receives. A hook prints it at session start. Sentences run under 20 words and express one idea. Use the active voice, and use only the infinitive, the imperative, and simple tenses. Use a verb rather than a noun made from a verb. Keep the technical content exactly as precise as it was, and simplify only the language around it. Describe the design as it stands now rather than the approaches you discarded.

The structural contract CI enforces on a pull request:

- The sections `## What changed`, `## Why`, and `## Verification` exist and are not empty.
- The prose references the issue the change resolves, as `#N` or its URL.
- Verification pastes the command you ran and its output in a fenced block under `## Verification`. It identifies the data it read, as a URL or catalog path.
- A change that alters no behavior ticks the waiver checkbox instead. Keep its wording intact because the check matches the phrase "does not alter behavior".

Good evidence shows the fix works against real data. Proving a command exits zero is not enough. Take the failing command from the issue, run it against the same catalog, and show it now succeeds. A wall of pytest output does not count.

Issues follow the same shape. A bug report shows the failure and identifies the data. Write a feature request to show what the current tool cannot do, or what the workaround costs. A task states the outcome and the command that proves it is done.

Each repo uses the org issue template. The language itself is checked before a body is ever filed: `.claude/hooks/writing_check.py` runs on `gh issue create` and `gh pr create`, and reports the specific problems it found. Run `writing_check.py --print-rules` to read the rules. When it is wrong about a line, say so in the body with `<!-- ste-ok: RULE_ID why this is correct -->`. Dependabot is exempt from the CI check.

That check matches words and punctuation, but cannot assess tone or padding. It also cannot assess prose that argues for its own value. Passing proves nothing about how the body reads. Read what you wrote before you file it. Cut sentences that only make the change sound good.

## Documentation

Agents writing or restructuring documentation follow two exemplars named in [norms/docs.md](https://github.com/portolan-sdi/portolan-ops/blob/main/norms/docs.md). [obstore](https://github.com/developmentseed/obstore) demonstrates a concise, human-readable README that delegates to good docs elsewhere. [scaffold-docs-skill](https://github.com/dbreunig/scaffold-docs-skill) shows how to build docs that have a clear human-facing surface, maintain examples via tests so they never drift, and auto-generate API docs instead of duplicating them. Both make documentation easy to maintain and easy to update. Draft top-down with human review between layers. Do not draft a README from a generic template or from memory.

These rules apply to every docs change. Use sentence-case headings without emoji. Use absolute dates like "in July 2026", never "recently". Run every command example against the released tool before you publish it.

## Voice and messaging

Every written artifact follows the prose rules in [norms/prose.md](https://github.com/portolan-sdi/portolan-ops/blob/main/norms/prose.md). Vale checks Markdown and website copy. The writing hook checks the prose in issues and pull requests. Apply the rules while drafting, not as cleanup.

Before drafting substantial public copy like a README, a docs page, or an announcement, fetch and read [norms/prose.md](https://github.com/portolan-sdi/portolan-ops/blob/main/norms/prose.md) and [copy/messaging.md](https://github.com/portolan-sdi/portolan-ops/blob/main/copy/messaging.md) in full. If you cannot fetch them, say so and stop. Write from the actual files, not from memory.

How Portolan is described comes from [copy/messaging.md](https://github.com/portolan-sdi/portolan-ops/blob/main/copy/messaging.md) alone.

## Org-wide facts

The canonical homepage is https://www.portolan-sdi.org/. Canonical URLs live in [copy/urls.md](https://github.com/portolan-sdi/portolan-ops/blob/main/copy/urls.md). Do not hardcode variants.

Community discussion happens in the [Portolan Google Group](https://groups.google.com/g/portolan) and the [Portolan channel](https://cloudnativegeo.slack.com/archives/C0A1JBH9529) in Cloud-Native Geo Slack. Planning happens in [org-level GitHub projects](https://github.com/orgs/portolan-sdi/projects/1).

## Contribution rules

The [AI policy](https://github.com/portolan-sdi/portolan-ops/blob/main/policies/AI_POLICY.md) applies to every contribution. An agent may draft the diff and the pull request body. A human must read, understand, and approve both before review is requested. Agents never open PRs, post comments, or take action in shared spaces without human approval.

Follow the [contributing guide](https://github.com/portolan-sdi/portolan-ops/blob/main/policies/CONTRIBUTING.md) and the [code of conduct](https://github.com/portolan-sdi/portolan-ops/blob/main/policies/CODE_OF_CONDUCT.md).

## Sync discipline

Files between `ops-sync` markers are synced from [portolan-ops](https://github.com/portolan-sdi/portolan-ops). They are overwritten on every sync run. To change one, edit it in portolan-ops, never in place.

One canonical home per fact. If a value like a color, URL, or policy line exists in portolan-ops, link to it rather than copying it.
<!-- ops-sync:end -->

<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# Portolan website

Rules for this site. The org norms above apply here too.

## How Portolan is described

Identity, framing, and the words used for Portolan come from
[copy/messaging.md](https://github.com/portolan-sdi/portolan-ops/blob/main/copy/messaging.md)
in portolan-ops. Read it before writing site copy.

## Visual system

Brand values (palette, type, logos) come from
[brand/](https://github.com/portolan-sdi/portolan-ops/blob/main/brand/) in
portolan-ops. The rules below cover how this site spends them.

- **Color tokens:** Use CSS variables from `globals.css`. Never hardcode hex except in SVG and the map canvas.
- **Light mode only.** Dark mode was removed in July 2026. There is no `[data-theme]` switch, no `ThemeToggle`, and no dark token block. Do not reintroduce a dark theme or a theme toggle.
- **Type scale (single source of truth):** Use the named utilities generated from `--text-*` tokens in `globals.css`, never arbitrary sizes like `text-[13px]`. Eight steps, smallest first: `text-eyebrow`, `text-small`, `text-body`, `text-lead`, `text-card-title`, `text-feature`, `text-section`, `text-hero`. Headings and lead text are fluid via `clamp()`. The scale was cut from thirteen steps in August 2026. Do not add a step back: the removed ones (`micro`, `body-lg`, `card-title-lg`, `section-sm`, `hero-sm`) sat within 0.5px of a neighbor or inverted the heading hierarchy. `text-lead` caps at 18px so `text-card-title` outranks it at every width.
- **Corners are square.** All `--p-r-*` radius tokens are `0px`, so every button, input, and content block has 90-degree corners. Nothing is rounded or pill-shaped. The only circle allowed is a loading spinner, which has to spin.
- **Surfaces are flat, rules are black.** Shadow tokens render as `none` or a single rule, never a glassy drop shadow. Separate content with rules, not cards or soft background bands. Structural rules (`border-p-line`) are near-black ink. There is no `border-p-line-strong`: it carried the same hex as `border-p-line`, so it named a weight a color token cannot hold. Where a rule needs more weight, thicken the border. The soft tier (`border-p-line-soft`, `#d6d5ca`) is only for interior separators inside an already-bordered block. The heavy black line weight is deliberate, so do not lighten it back to pale hairlines. No `--p-bg-soft` section band on the page: the talks section runs a solid `--p-primary` band instead.
- **Annotated figures are the sanctioned illustration motif.** Technical diagrams drawn as inline SVG in `--p-primary` strokes with tiny mono labels, dashed leader lines, a faint blue graph-paper wash, and a `Fig. N` caption row (see `PipelineFigure` in the how-it-works section). Figures never mirror in RTL (`dir="ltr"`), and format and tool names inside figures stay Latin. Compass roses and rhumb lines remain banned.
- **Section kickers:** mono, `text-p-ink-3`, the label string only. No `NN ·` index prefixes (numbers are reserved for real sequences like the how-it-works steps), no `// EYEBROW` punctuation, no uppercase, no wide tracking.
- **No terminal mockups.** The fake-terminal blocks and their `--term-*` tokens were removed in July 2026. Do not reintroduce terminal or code-session mockups anywhere on the site.
- **Logo:** Two-pennant SVG in `PortolanLogo`, rendered in a **solid** `--p-primary` fill, no gradient.

## Layout and responsiveness

- **Mobile-first, always.** Start from the single-column small-screen layout, then add `sm:` / `md:` / `lg:` breakpoints. Never write a desktop-only layout.
- **Section padding:** sections use `px-[var(--p-pad-section-x)]` and `py-[var(--p-pad-section-y)]` (fluid `clamp()` tokens). Do not use the fixed `--p-pad-xl` for section padding.
- **Grids collapse:** multi-column grids start at `grid-cols-1` and step up (for example `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`).
- **Page header band:** every route except the homepage opens with `PageHero` in `page-hero.tsx`. It is the homepage hero, shortened and held still: the same glyph relief map, the same `--hero-scrim`, the same headline treatment. The map takes `still` so it does not drift, because the homepage carries the one moving element on the site. The band owns the page's `<h1>`, so the section below it sets no second one and opens with a tightened `pt-[clamp(28px,3.5vw,48px)]` instead of the full section padding. A two-part headline passes `subtitle`, which sets inside the `<h1>` so it inherits the heading font and differs only in weight and size.
- **Shared chrome:** primary navigation is a collapsible left **side rail**, `SiteShell` in `site-rail.tsx`, which wraps the page. It replaced the old minimal header and centered footer (both removed July 2026, `SiteHeader`/`SiteFooter` are gone, do not reintroduce them or inline `<header>` / `<footer>` markup). The rail is pinned from `md` up (content is inset by `--p-rail`). "Collapse" slides it off-canvas and a mono "» Index" handle restores it. Below `md` it is an off-canvas drawer opened from a mono "Index" button in a slim sticky top bar, the word, never a hamburger icon. The rail holds, top to bottom: the logo linking home, the in-page section anchors (labels reuse each section's eyebrow, active section highlighted in `--p-primary`), an "External" group (Docs↗, GitHub↗), then a pinned foot with the locale control and a compact "«" collapse button on one row (no tagline, no CTA, both removed July 2026). Navigation lives only in the rail. There is no separate footer nav, and only real links, never dead spans. On solid `--p-bg` with black rules, no frosted `backdrop-blur`. Rail transforms are direction-aware (the rail hides toward its own inline-start edge). Do not mirror the logo.

## Blog

Blog posts are MDX. The pipeline is `@next/mdx` with no remark or rehype
plugins, because Turbopack compiles MDX in Rust and cannot receive a
JavaScript plugin function.

- **Post bodies** live at `src/content/blog/<slug>.mdx`. The route
  `src/app/[locale]/blog/[slug]/page.tsx` imports them by slug and sets
  `dynamicParams = false`, so an unknown slug is a 404.
- **Post metadata** lives in `src/lib/blog.ts`. A new post needs an entry in
  `POSTS` and a matching MDX file. The index, the sitemap, and
  `generateMetadata` all read that list.
- **Posts are English only.** Post titles and summaries live in
  `src/lib/blog.ts`, not in `messages/`. This is the one exception to the rule
  that every user-facing string lives in `messages/`. A reader on `/es/` or
  `/ar/` gets the English body under a translated notice. All page chrome
  around the post stays translated in all three locales.
- **Body styling** comes from `src/mdx-components.tsx`, the element map. There
  is no `prose` class and no typography plugin. Do not add one. Style a new
  element by adding it to that map.
- **Media** uses `PostFigure` in `src/components/blog/post-figure.tsx`. Omit
  its `src` while an asset is missing and it draws a framed placeholder that
  names the pending file.
- **Measure:** a post body runs `max-w-[68ch]`, narrower than the 1240px
  content column the rest of the site uses. A lead or intro paragraph under a
  page title takes no measure cap and runs the full column.

## Tech stack

- Next.js 16+ App Router with TypeScript
- Tailwind CSS (pure utilities, no `@apply`)
- MDX via `@next/mdx` for blog post bodies
- next-intl for i18n (English default, Spanish at `/es/`)
- pnpm for package management
- Deploying to Vercel at portolan-sdi.org

## What NOT to do

- Don't add a "mission" or "about" section to the homepage
- Don't reintroduce the install button in the header
- Don't add emoji (except Unicode marks: ↗, →, ·)
- Don't add icons to nav items
- Don't introduce CSS-in-JS libraries
- Don't add filler content
- Don't use arbitrary font-size values (`text-[13px]`); use the type scale
- Don't inline header/footer markup or reintroduce `SiteHeader`/`SiteFooter`; navigation is the `SiteShell` side rail
- Don't reintroduce the "AI-y" look: gradient text/fills, gradient or shadowed buttons, glassy drop shadows, rounded bento cards, pill-shaped tags, circular status dots, `// EYEBROW` labels, or soft alternating background bands.
- Don't reintroduce the second-wave "AI-y" tells removed in the bespoke pass: typewriter/rotating hero headlines, `NN ·` numbered section kickers, numbers on non-sequence card grids, macOS traffic-light dots on terminals, stacked big-number hero stat blocks (live stats render as one mono log-line), or a frosted translucent header.
- Don't propose or reintroduce the rhumb-line / compass-rose motif in any form. It was tried repeatedly and explicitly rejected.
- Don't give every card in a grid identical anatomy (number + title + body + tag). Ragged is deliberate.

## i18n

- Default locale: English (no URL prefix)
- Spanish: `/es/` prefix · Arabic: `/ar/` prefix (RTL)
- Translation files in `messages/` (`en.json`, `es.json`, `ar.json`)
- Use `useTranslations` hook in client components

### Translation contract (required)

- Every user-facing string lives in `messages/`. Never hardcode copy in components.
- When you add or change a string, update **all three** files (`en`, `es`, `ar`) under
  the **same key**. Key sets must stay identical across locales.
- Follow `docs/i18n/glossary.md`. Keep product and format names (Portolan, STAC,
  GeoParquet, COG, S3, ...) in Latin in every locale.
- Digits are always Latin (0-9), including in Arabic.
- No em dashes, colons, or semicolons in Spanish or Arabic copy.
- Typeable identifiers inside prose (formats like GeoParquet/COG/STAC/PMTiles, file
  names, CLI commands, `Apache-2.0`) are wrapped in `<m>…</m>` tags in `messages/*.json`
  and rendered mono via `t.rich(key, { m: monoChunk })` (`monoChunk` from `./ui`).
  Product names (Portolan, DuckDB, ...) stay sans. Tags must stay identical across all
  three locales, and any key carrying `<m>` tags must be rendered with `t.rich`, never
  plain `t()`.

### RTL rules (Arabic)

- Use Tailwind **logical** utilities in shared UI (`ps/pe`, `ms/me`, `text-start/end`,
  `border-s/e`, `rounded-s/e`, `inset-s/e`), never physical `pl/pr/ml/mr/left/right`.
  Prefer `gap-*` over `space-x-*`.
- Reserve `rtl:` variants for mirroring directional icons (use `<DirArrow>`).
- Never mirror the logo, the map/dither canvas, or terminal/code blocks. Terminal and
  code blocks stay `dir="ltr"`.
- Wrap pure-Latin standalone values (names, versions, license, repo) in `<Ltr>` so they
  stay correctly ordered inside Arabic text.
- Arabic always renders in Cairo (Hanken Grotesk has no Arabic glyphs). On RTL pages the
  `--p-sans` token re-points to Cairo in `globals.css`, so body, headings, and the
  `font-sans` utility all resolve to Cairo. Cairo is also the Arabic-glyph fallback in
  the base sans stack, so stray Arabic on an LTR page (for example the language switcher)
  still renders Cairo. Never hardcode `font-family`, rely on the tokens.
- Buttons (`Btn`) are mono, uppercase, and letterspaced (`tracking-[0.08em]`), neutralized
  with `rtl:tracking-normal` because letterspacing breaks Arabic's connected script.
- `<html lang dir>` is set per locale in `src/app/[locale]/layout.tsx` via
  `getDirection(locale)`. Do not reintroduce `<html>` into the root layout.


<claude-mem-context>
# Memory Context

# [portolan] recent context, 2026-08-27 5:45pm GMT+2

Legend: 🎯session 🔴bugfix 🟣feature 🔄refactor ✅change 🔵discovery ⚖️decision 🚨security_alert 🔐security_note
Format: ID TIME TYPE TITLE
Fetch details: get_observations([IDs]) | Search: mem-search skill

Stats: 10 obs (3,019t read) | 24,238t work | 88% savings

### Aug 27, 2026
S9970 Fix style picker sparse-column handling; finalize Overture defect documentation strategy; re-pick all collections (Aug 27, 3:36 PM)
S9971 Update ETA and risk assessment for completing style picker fixes and catalog validation (Aug 27, 3:39 PM)
S9972 Monitor style re-pick progress; assess fix effectiveness and identify visual edge cases (Aug 27, 3:42 PM)
S9974 Complete style picker workflow; prepare for Gate 2 visual review with thumbnail re-render (Aug 27, 3:50 PM)
S9975 Validate Portolan Overture catalog with styles and thumbnails in place; review Gate 2 thumbnail cards for rendering issues (Aug 27, 3:56 PM)
S9973 Complete style picker workflow; prepare for Gate 2 visual review with thumbnail re-render (Aug 27, 3:56 PM)
S9976 Improve thumbnails in nlebovits/overture-portolan Portolan catalog (feat/all-collections branch) — 15 collections with generated styles and rendered tiles need visual refinement. (Aug 27, 3:57 PM)
S9977 Complete and submit Codex's thumbnail art direction work; polish and finalize the full Overture catalog for merge and deployment (Aug 27, 4:01 PM)
S9978 Complete Codex's thumbnail art direction work and finalize the full Overture catalog for merge and deployment (Aug 27, 5:29 PM)
25657 5:34p ✅ Live Gate Fixed: Switched from portolan-cli to rashid; CORS Headers Now Present
25658 " 🔵 Discrepancy: PTL-LIV-004/005 Present Locally, Absent in Deployed Version
25659 " 🔵 JSON Structure Mismatch: Gate Expects report.data.findings, Rashid Provides report.findings
25656 " 🔵 Registry coverage endpoint missing cache in production
25661 5:36p 🔵 Workflow Out of Sync: Pages Workflow Still Installs portolan-cli, Test Expects rashid
25662 " ✅ GitHub Pages Workflow Updated to Install Rashid from requirements-ci.txt
25663 " ✅ Commit: Fix Live Gate Validator; Switch from portolan-cli to rashid
25665 " ✅ PR Body Revision: Writing Issues Reduced from 3 to 1 Blocking
25666 " ✅ Pull Request #6 Opened: Fix for Live Gate Validator
S9979 Fix live hosting gate failures and verify deployment; diagnose and resolve two bugs preventing live validation from passing in CI environment (Aug 27, 5:36 PM)
25667 5:38p 🔴 Registry coverage endpoint cache regression fixed with force-static

Access 24k tokens of past work via get_observations([IDs]) or mem-search skill.
</claude-mem-context>