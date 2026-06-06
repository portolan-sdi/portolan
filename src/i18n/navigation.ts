import { createNavigation } from "next-intl/navigation";
import { routing } from "./routing";

// Locale-aware navigation APIs. Use this Link (not next/link) for internal
// navigation so the active locale prefix (e.g. /es) is preserved.
export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
