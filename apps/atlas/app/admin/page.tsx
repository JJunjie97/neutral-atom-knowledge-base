import type { Metadata } from "next";
import AdminWorkspace from "./AdminWorkspace";
import "./admin.css";

export const metadata: Metadata = {
  title: "数据库管理",
  description:
    "在本机安全地检索、校对与维护中性原子量子计算文献数据库。",
};

export default function AdminPage() {
  return <AdminWorkspace />;
}
