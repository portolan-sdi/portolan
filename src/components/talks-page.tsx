"use client";

import { useTranslations } from "next-intl";
import { useRevealed } from "@/hooks/use-revealed";
import { PageHero } from "./page-hero";
import { AWAY_ITEMS, SiteShell } from "./site-rail";
import { DirArrow, Ltr, monoChunk } from "./ui";

// Talks & demos as a source wall: white paper cards, ruled in black, carrying a
// real screenshot of the thing they link to. Every card shares one frame and
// one crop, screenshot first. Every second column drops by a single fixed
// step, so the stagger is regular rather than per-card. A wrapper carries that
// step as a translate, which leaves the grid rows unchanged and so keeps the
// offset from opening a gap under the column beside it or from pushing a card
// into the row below. Column parity differs per breakpoint, so the drop is
// keyed to the column count at each one. The wrapper owns the translate
// because the card itself spends transform on the hover lift. A solid primary
// band runs behind the wall, and blue otherwise appears only on the title
// arrow and the focus ring. Hovering lifts a card off the page.
//
// This was a homepage section until the site went multi-page. It now owns a
// route, so the page header band above carries the h1 and this section carries
// no id (the rail entry is named by activeId).

type Item = {
  key: string;
  href: string;
  src: string;
};

const ITEMS: Item[] = [
  {
    key: "bolzanoTalk",
    href: "https://cayetanobv.github.io/ogc-metadata-summit-bolzano/",
    src: "/img/talks/ogc-bolzano.png",
  },
  {
    key: "yharbyTalk",
    href: "https://yharby.github.io/cng-japan-2026/#/1",
    src: "/img/talks/cng-japan.png",
  },
  {
    key: "holmesTalk",
    href: "https://cholmes.github.io/open-geodag-presentation/",
    src: "/img/talks/open-geodag.png",
  },
  {
    key: "nextSdi",
    href: "https://jatorre.github.io/carto-ogc-helsinki/",
    src: "/img/talks/next-sdi.jpg",
  },
  {
    key: "finlandDemo",
    href: "https://jatorre.github.io/carto-ogc-helsinki/webapp/",
    src: "/img/talks/finland-sdi.png",
  },
  {
    key: "costCalc",
    href: "https://cholmes.github.io/open-geodag-presentation/calculator.html",
    src: "/img/talks/cost-calculator.png",
  },
];

function Shot({ item, alt }: { item: Item; alt: string }) {
  return (
    <div className="aspect-[16/7.5] overflow-hidden border-b border-p-line bg-p-ink">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={item.src}
        alt={alt}
        loading="lazy"
        decoding="async"
        className="h-full w-full object-cover object-top"
      />
    </div>
  );
}

export function TalksPage() {
  const t = useTranslations("talks");
  const { ref, revealed } = useRevealed<HTMLElement>();

  return (
    <SiteShell navItems={AWAY_ITEMS} activeId="talks">
      <PageHero title={t("title")} />

      <section
        ref={ref}
        data-in={revealed}
        className="tk-wall relative isolate overflow-hidden px-[var(--p-pad-section-x)] pb-[var(--p-pad-section-y)] pt-[clamp(28px,3.5vw,48px)]"
      >
        {/* The band is positioned as a share of the section, so it keeps
            sitting behind the wall as translations change the card heights.
            The headline moved to the page header band above, so the wall now
            starts at the top of this section and the band sits higher. */}
        <div
          aria-hidden
          className="tk-band absolute inset-x-0 top-[38%] -z-10 h-[clamp(150px,16vw,210px)] bg-p-primary"
        />

        <div className="mx-auto max-w-[1240px]">
          <div
            style={
              { "--tk-step": "clamp(36px,5vw,72px)" } as React.CSSProperties
            }
            className="grid grid-cols-1 items-start gap-5 sm:grid-cols-2 sm:pb-[var(--tk-step)] xl:grid-cols-3"
          >
            {ITEMS.map((item, i) => {
              const alt = t(`items.${item.key}.alt`);
              const drop = [
                i % 2 === 1
                  ? "sm:translate-y-[var(--tk-step)]"
                  : "sm:translate-y-0",
                i % 3 === 1
                  ? "xl:translate-y-[var(--tk-step)]"
                  : "xl:translate-y-0",
              ].join(" ");
              return (
                <div key={item.key} className={drop}>
                  <a
                    href={item.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ animationDelay: `${i * 0.09}s` }}
                    className="tk-card group flex flex-col border border-p-line bg-p-paper text-p-ink focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-4 focus-visible:outline-p-primary"
                  >
                    <Shot item={item} alt={alt} />

                    <div className="p-5">
                      <p className="mb-4 font-mono text-small text-p-ink-3">
                        <Ltr>{t(`items.${item.key}.attribution`)}</Ltr>
                      </p>

                      {/* The card is the link, so the mark rides the title. */}
                      <h2 className="text-card-title font-bold leading-[1.2] tracking-[-0.02em] text-pretty">
                        <Ltr>{t(`items.${item.key}.title`)}</Ltr>{" "}
                        <span className="inline-block text-p-primary transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 rtl:group-hover:-translate-x-0.5 motion-reduce:transition-none motion-reduce:group-hover:translate-x-0 motion-reduce:group-hover:translate-y-0">
                          <DirArrow kind="external" />
                        </span>
                      </h2>

                      <p className="mt-3 text-small leading-[1.55] text-p-ink-2 text-pretty">
                        {t.rich(`items.${item.key}.description`, {
                          m: monoChunk,
                        })}
                      </p>
                    </div>
                  </a>
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </SiteShell>
  );
}
