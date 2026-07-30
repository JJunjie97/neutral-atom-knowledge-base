import type { Metadata } from "next";
import LiteratureExplorer from "./components/LiteratureExplorer";
import { absoluteUrl } from "./site-config";

export const metadata: Metadata = {
  title: "\u4e2d\u6027\u539f\u5b50\u91cf\u5b50\u8ba1\u7b97",
  description:
    "\u63a2\u7d22 637 \u7bc7\u6838\u5fc3\u6587\u732e\u4e0e 14,000 \u4f59\u7bc7\u5b8c\u6574\u53c2\u8003\u6587\u732e\u7684\u5f15\u7528\u7f51\u7edc\u3001\u4e3b\u9898\u7fa4\u843d\u548c\u65f6\u95f4\u8109\u7edc\u3002",
  openGraph: {
    title: "\u4e2d\u6027\u539f\u5b50\u91cf\u5b50\u8ba1\u7b97 \u00b7 \u6587\u732e\u661f\u56fe",
    description:
      "\u4ea4\u4e92\u5f0f\u63a2\u7d22\u4e2d\u6027\u539f\u5b50\u91cf\u5b50\u8ba1\u7b97\u9886\u57df\u7684\u5f15\u7528\u7f51\u7edc\u4e0e\u65f6\u95f4\u8109\u7edc\u3002",
    images: [absoluteUrl("/og.png")],
  },
};

export default function Home() {
  return <LiteratureExplorer />;
}
