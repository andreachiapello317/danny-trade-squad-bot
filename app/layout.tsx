import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { DeskShell } from "@/components/desk-shell";
import { SquadProvider } from "@/components/squad-provider";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "BotSquad — desk Danny",
  description:
    "Squadra che legge i grafici della newsletter di Danny Chang, vota i setup di buy e manda il carrello da 10 solo al CEO. Su Telegram scrive solo il Sender.",
  applicationName: "BotSquad",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "BotSquad",
    statusBarStyle: "black-translucent",
  },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  themeColor: "#09090b",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="it"
      className={`dark ${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-zinc-950 font-sans text-zinc-100">
        <SquadProvider>
          <DeskShell>{children}</DeskShell>
        </SquadProvider>
      </body>
    </html>
  );
}
