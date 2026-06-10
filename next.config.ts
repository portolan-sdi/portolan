import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  // The /quickstart route was folded into the homepage; these run before the
  // next-intl proxy so all three locales land on the right anchor.
  async redirects() {
    return [
      {
        source: "/quickstart",
        destination: "/#quickstart",
        permanent: true,
      },
      {
        source: "/:locale(es|ar)/quickstart",
        destination: "/:locale#quickstart",
        permanent: true,
      },
    ];
  },
};

export default withNextIntl(nextConfig);
