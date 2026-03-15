import type { Metadata } from "next";
import { Instrument_Sans, Fira_Code, Instrument_Serif } from "next/font/google";
import localFont from "next/font/local";
import { Toaster } from "@/components/ui/sonner";
import { Providers } from "@/components/providers";
import "./globals.css";

const instrumentSans = Instrument_Sans({
  variable: "--font-instrument-sans",
  subsets: ["latin"],
});

const firaCode = Fira_Code({
  weight: "400",
  variable: "--font-fira-code",
  subsets: ["latin"],
});

const instrumentSerif = Instrument_Serif({
  weight: "400",
  style: "italic",
  variable: "--font-instrument-serif",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Benchy - AI Performance Optimizer",
  description: "Analyze, benchmark, and optimize your code with AI",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`dark ${instrumentSans.variable} ${firaCode.variable} ${instrumentSerif.variable}`}>
      <body className="antialiased bg-dark text-light">

        <Providers>
          {children}
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
