import type { Metadata } from "next";
import { publicUrl } from "./site-config";
import "./globals.css";
import "./atlas.css";
import "./local-graph.css";
import "./translation.css";

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000",
  ),
  title: {
    default: "\u4e2d\u6027\u539f\u5b50\u91cf\u5b50\u8ba1\u7b97 \u00b7 \u6587\u732e\u661f\u56fe",
    template: "%s \u00b7 \u6587\u732e\u661f\u56fe",
  },
  description:
    "\u4e2d\u6027\u539f\u5b50\u91cf\u5b50\u8ba1\u7b97\u9886\u57df\u7684\u4ea4\u4e92\u5f0f\u6587\u732e\u5173\u7cfb\u7f51\u7edc\u3001\u53d1\u5c55\u8109\u7edc\u4e0e\u672c\u5730\u6570\u636e\u5e93\u7ba1\u7406\u5de5\u5177\u3002",
  icons: {
    icon: publicUrl("/favicon.svg"),
    shortcut: publicUrl("/favicon.svg"),
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
