import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SmartBite — идеи для ужина",
  description: "Подбор рецептов по продуктам и предпочтениям",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
