import type { Locale } from "./routing";

// The Intl Locale Info API is available at runtime (Node 21+ / modern V8) but
// is not yet in the TypeScript lib types. Both the current method form
// (getTextInfo()) and the older accessor form (textInfo) are handled.
type LocaleTextInfo = { direction: "ltr" | "rtl" };
type LocaleWithTextInfo = Intl.Locale & {
  getTextInfo?: () => LocaleTextInfo;
  textInfo?: LocaleTextInfo;
};

// Text direction for a locale, derived from the BCP-47 tag via the native
// Intl API (no rtl-detect dependency). Runs server-side in the locale layout.
export function getDirection(locale: Locale | string): "ltr" | "rtl" {
  try {
    const loc = new Intl.Locale(locale) as LocaleWithTextInfo;
    const direction = loc.getTextInfo?.().direction ?? loc.textInfo?.direction;
    return direction === "rtl" ? "rtl" : "ltr";
  } catch {
    return "ltr";
  }
}
