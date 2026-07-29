import type { Metadata } from "next";
import "./globals.css";
import "./atlas.css";

export const metadata: Metadata = {
  title: {
    default: "中性原子量子计算 · 文献星图",
    template: "%s · 文献星图",
  },
  description:
    "中性原子量子计算领域的交互式文献关系网络与时间线。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
