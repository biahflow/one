import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { headers } from "next/headers";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "localhost:3000";
  const protocol = requestHeaders.get("x-forwarded-proto") ?? "http";
  const origin = `${protocol}://${host}`;

  return {
    title: "Portal Labs | Portal do Cliente",
    description: "Acompanhe projetos, resultados e decisões em um só lugar.",
    icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
    openGraph: {
      title: "Portal do Cliente | Portal Labs",
      description: "Projetos, resultados e decisões com IA.",
      url: origin,
      siteName: "Portal Labs",
      locale: "pt_BR",
      type: "website",
      images: [{ url: `${origin}/og.png`, width: 1200, height: 630, alt: "Portal do Cliente — Portal Labs" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "Portal do Cliente | Portal Labs",
      description: "Projetos, resultados e decisões com IA.",
      images: [`${origin}/og.png`],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pt-BR">
      <body className={`${inter.variable} antialiased`}>{children}</body>
    </html>
  );
}
