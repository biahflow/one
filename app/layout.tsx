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
    title: "One",
    description: "Acompanhe projetos, resultados e decisões em um só lugar.",
    // O tile do favicon serve as três superfícies fora da tela do produto que o DAP r3
    // reservou para ele (§01, decisão 2): aba, atalho de tela e cartão de compartilhamento.
    // `apple` é PNG porque o Safari ignora SVG em `apple-touch-icon` — é a única razão de
    // haver um raster do que já existe em vetor.
    icons: {
      icon: "/favicon.svg",
      shortcut: "/favicon.svg",
      apple: "/apple-touch-icon.png",
    },
    manifest: "/manifest.webmanifest",
    openGraph: {
      title: "One",
      description: "Projetos, resultados e decisões com IA.",
      url: origin,
      siteName: "One",
      locale: "pt_BR",
      type: "website",
      images: [{ url: `${origin}/og.png`, width: 1200, height: 630, alt: "One — by Biahflow" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "One",
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
