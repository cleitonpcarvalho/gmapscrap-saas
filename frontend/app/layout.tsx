import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GmapScrap",
  description: "Coletor web de leads do Google Maps"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
