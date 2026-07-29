import type { Metadata } from "next";
import LiteratureExplorer from "./components/LiteratureExplorer";

export const metadata: Metadata = {
  title: "中性原子量子计算",
  description:
    "探索 637 篇核心文献与 14,072 篇完整参考文献的引用网络、主题群落和时间脉络。",
  openGraph: {
    title: "中性原子量子计算",
    description:
      "交互式探索中性原子量子计算领域的引用网络与时间脉络。",
    images: ["/og.png"],
  },
};

export default function Home() {
  return <LiteratureExplorer />;
}
