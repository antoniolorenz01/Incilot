import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import { GeistPixelGrid } from "geist/font/pixel";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono-family",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "IncidentPilot",
  description: "An agent that investigates incidents, proposes a fix and applies it once you approve.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en-GB"
      className={`dark ${jetbrainsMono.variable} ${GeistPixelGrid.variable} h-full antialiased`}
      // Extensions such as Dark Reader add attributes to <html> before React loads.
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col font-mono">
        {children}
        <Toaster theme="dark" />
      </body>
    </html>
  );
}
