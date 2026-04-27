import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GPMPG",
  description: "General Purpose Marketing Promotions Generator",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
