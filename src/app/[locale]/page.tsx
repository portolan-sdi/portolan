import { setRequestLocale } from "next-intl/server";
import { HomePage } from "@/components";

interface PageProps {
  params: Promise<{ locale: string }>;
}

export default async function Home({ params }: PageProps) {
  const { locale } = await params;
  setRequestLocale(locale);

  return <HomePage />;
}
