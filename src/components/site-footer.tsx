import { useTranslations } from "next-intl";
import { PortolanLogo } from "./portolan-logo";
import { Ltr } from "./ui";

export function SiteFooter() {
  const t = useTranslations();
  return (
    <footer className="px-[var(--p-pad-section-x)] py-[var(--p-pad-lg)] border-t border-p-line-soft flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 text-small text-p-ink-3">
      <PortolanLogo size={22} />
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <span>{t("footer.openGovernance")}</span>
        <span><Ltr>{t("footer.license")}</Ltr></span>
        <span><Ltr>{t("footer.repo")}</Ltr></span>
      </div>
    </footer>
  );
}
