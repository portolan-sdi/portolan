import { setRequestLocale } from "next-intl/server";
import { QuickstartPage } from "@/components/quickstart-page";

interface PageProps {
  params: Promise<{ locale: string }>;
}

export default async function Quickstart({ params }: PageProps) {
  const { locale } = await params;
  setRequestLocale(locale);

  return <QuickstartPage />;
}
