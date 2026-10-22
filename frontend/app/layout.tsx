import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SmartBite — идеи для вашей кухни",
  description: "Рецепты с учётом продуктов, пожеланий и доступной техники",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
