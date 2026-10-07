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
  description: "Un agente que investiga incidentes, propone la solución y la ejecuta con tu aprobación.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="es"
      className={`dark ${jetbrainsMono.variable} ${GeistPixelGrid.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col font-mono">
        {children}
        <Toaster theme="dark" />
      </body>
    </html>
  );
}
