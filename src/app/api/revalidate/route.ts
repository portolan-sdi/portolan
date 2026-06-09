import { NextRequest, NextResponse } from "next/server";
import { revalidateTag } from "next/cache";
import { CATALOGS_CACHE_TAG } from "@/lib/catalogs";

const REVALIDATE_SECRET = process.env.REVALIDATE_SECRET;

// On-demand revalidation for the catalog registry. The portolan-registry CI
// posts here right after it publishes a fresh exports/catalogs.json so the
// browsable catalog list updates immediately instead of waiting out the
// hourly ISR window. Authenticated with a shared bearer secret.
export async function POST(req: NextRequest) {
  if (!REVALIDATE_SECRET) {
    return NextResponse.json(
      { error: "Server not configured for revalidation" },
      { status: 503 }
    );
  }

  const auth = req.headers.get("authorization");
  if (auth !== `Bearer ${REVALIDATE_SECRET}`) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  // "max" gives stale-while-revalidate semantics: the cached list is marked
  // stale and refreshed in the background on the next visit, rather than
  // forcing a blocking cache miss.
  revalidateTag(CATALOGS_CACHE_TAG, "max");

  return NextResponse.json({
    revalidated: true,
    tag: CATALOGS_CACHE_TAG,
  });
}
