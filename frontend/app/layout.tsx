import type { Metadata, Viewport } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';

/* next/font self-hosts these at build time: no runtime request to Google, no layout
   shift, and nothing about the user leaks to a third party — consistent with the rest
   of the app's privacy posture.

   Inter is chosen for its tabular figures (see `tabular-nums` in globals.css): in a
   data app, digits must sit in fixed-width columns or numbers stop being comparable
   down a table. JetBrains Mono has a tall x-height and a slashed zero, which is what
   makes generated SQL readable at 12px. */
const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-sans',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-mono',
});

export const metadata: Metadata = {
  title: 'Data Q&A',
  description: 'Ask questions of your spreadsheets in plain English.',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="min-h-screen bg-slate-50">{children}</body>
    </html>
  );
}
