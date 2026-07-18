import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GmapScrap",
  description: "Coletor web de leads do Google Maps",
  icons: {
    icon: [
      { url: "/gmapscrap-favicon.png", type: "image/png" },
      { url: "/favicon.ico" }
    ],
    apple: [{ url: "/gmapscrap-favicon.png", type: "image/png" }]
  }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
