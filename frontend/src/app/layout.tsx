import type { Metadata } from "next";
import { Inter, Fira_Code } from "next/font/google";
import localFont from "next/font/local";
import { Toaster } from "@/components/ui/sonner";
import { Providers } from "@/components/providers";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const firaCode = Fira_Code({
  variable: "--font-fira-code",
  subsets: ["latin"],
});

const junicode = localFont({
  src: "../../public/fonts/Junicode-BoldItalic.ttf",
  variable: "--font-junicode",
  weight: "700",
  style: "italic",
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
    <html lang="en" className={`dark ${inter.variable} ${firaCode.variable} ${junicode.variable}`}>
      <body className="antialiased bg-dark text-light">

        <Providers>
          {children}
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
