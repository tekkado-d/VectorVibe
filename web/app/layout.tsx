import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://vector-vibe.vercel.app"),
  title: {
    default: "VectorVibe — search for clothes by describing anything",
    template: "%s · VectorVibe",
  },
  description:
    "Describe a person, a film, a mood or a feeling and find real clothes that match. No jargon, no filters to learn — just say what you mean.",
  openGraph: {
    title: "VectorVibe — search for clothes by describing anything",
    description:
      "Describe a person, a film, a mood or a feeling and find real clothes that match.",
    url: "https://vector-vibe.vercel.app",
    siteName: "VectorVibe",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "VectorVibe",
    description:
      "Describe a person, a film, a mood or a feeling and find real clothes that match.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-black text-white">
        {children}
      </body>
    </html>
  );
}