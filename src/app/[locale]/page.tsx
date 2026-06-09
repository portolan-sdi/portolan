import { setRequestLocale } from "next-intl/server";
import { HomePage } from "@/components";
import { getCatalogs } from "@/lib/catalogs";

interface PageProps {
  params: Promise<{ locale: string }>;
}

export default async function Home({ params }: PageProps) {
  const { locale } = await params;
  setRequestLocale(locale);

  let catalogs: Awaited<ReturnType<typeof getCatalogs>>["catalogs"] = [];
  try {
    const data = await getCatalogs();
    catalogs = data.catalogs;
  } catch (err) {
    console.error("Failed to fetch catalogs:", err);
  }

  return <HomePage catalogs={catalogs} />;
}
