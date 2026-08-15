import type { Metadata } from "next";

// Keeps /analytics out of Google. This is not security — it only asks
// well-behaved crawlers not to index the page. The ANALYTICS_KEY on the
// API is what actually protects the data.
export const metadata: Metadata = {
  title: "Analytics",
  robots: { index: false, follow: false },
};

export default function AnalyticsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}