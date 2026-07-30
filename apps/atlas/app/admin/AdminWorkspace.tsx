"use client";

import {
  ArrowLeft,
  BookOpen,
  Database,
  FileWarning,
  GitBranch,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Tags,
} from "lucide-react";
import { useState, useSyncExternalStore } from "react";
import { publicUrl } from "../site-config";
import {
  AdminApiClient,
  AdminApiError,
  type AdminClassification,
  type AdminSummary,
  type AdminTaxonomy,
  type WorkDetail,
  type WorkListPage,
  type WorkPatch,
} from "./admin-api";
import ConnectionPanel, {
  type ConnectionMode,
  type ConnectionState,
} from "./ConnectionPanel";
import RecordEditor from "./RecordEditor";
import { updatedAtFromDetail } from "./admin-types";
import WorkTable from "./WorkTable";

const DEFAULT_API_URL = "http://127.0.0.1:8765";
const SESSION_API_KEY = "nakb.admin.api-url";
const SESSION_TOKEN_KEY = "nakb.admin.token";
const PAGE_SIZE = 25;

function subscribeToRuntimeMode(): () => void {
  return () => undefined;
}

function browserRuntimeMode(): ConnectionMode {
  const localHosts = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);
  return localHosts.has(window.location.hostname) ? "local" : "public";
}

function sessionValue(key: string, fallback: string): string {
  return typeof window === "undefined"
    ? fallback
    : sessionStorage.getItem(key) || fallback;
}

const EMPTY_PAGE: WorkListPage = {
  items: [],
  total: 0,
  limit: PAGE_SIZE,
  offset: 0,
};

function messageFromError(cause: unknown): string {
  if (cause instanceof AdminApiError) {
    if (cause.status === 401 || cause.status === 403) {
      return "Token 无效或已过期，请使用管理服务本次启动时显示的新 token。";
    }
    if (cause.status === 409) {
      return "记录已被其他操作更新。请重新载入后再保存，避免覆盖较新的数据。";
    }
    return cause.message;
  }
  return cause instanceof Error ? cause.message : String(cause);
}

function SummaryCard({
  label,
  value,
  icon: Icon,
  accent,
}: {
  label: string;
  value: number | null;
  icon: typeof Database;
  accent?: boolean;
}) {
  return (
    <article className={`summary-card${accent ? " is-accent" : ""}`}>
      <Icon size={17} />
      <div>
        <strong>{value == null ? "—" : value.toLocaleString("zh-CN")}</strong>
        <span>{label}</span>
      </div>
    </article>
  );
}

export default function AdminWorkspace() {
  const mode = useSyncExternalStore<ConnectionMode>(
    subscribeToRuntimeMode,
    browserRuntimeMode,
    () => "detecting" as ConnectionMode,
  );
  const [connection, setConnection] = useState<ConnectionState>("offline");
  const [apiUrl, setApiUrl] = useState(() =>
    sessionValue(SESSION_API_KEY, DEFAULT_API_URL),
  );
  const [token, setToken] = useState(() => sessionValue(SESSION_TOKEN_KEY, ""));
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [summary, setSummary] = useState<AdminSummary | null>(null);
  const [taxonomy, setTaxonomy] = useState<AdminTaxonomy | null>(null);
  const [works, setWorks] = useState<WorkListPage>(EMPTY_PAGE);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [seedScope, setSeedScope] = useState<"all" | "seed" | "reference">("all");
  const [loadingWorks, setLoadingWorks] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<WorkDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editorRevision, setEditorRevision] = useState(0);
  const [notice, setNotice] = useState<{
    kind: "success" | "error";
    message: string;
  } | null>(null);

  function client(): AdminApiClient {
    return new AdminApiClient(apiUrl, token);
  }

  async function loadWorks(offset = 0, nextClient = client()) {
    setLoadingWorks(true);
    try {
      const page = await nextClient.listWorks({
        query,
        status,
        seed: seedScope,
        limit: PAGE_SIZE,
        offset,
      });
      setWorks(page);
    } catch (cause) {
      setNotice({ kind: "error", message: messageFromError(cause) });
    } finally {
      setLoadingWorks(false);
    }
  }

  async function connect() {
    if (mode !== "local") return;
    if (!token.trim()) {
      setConnectionError("请输入管理服务启动时显示的 session token。");
      return;
    }
    setConnection("connecting");
    setConnectionError(null);
    setNotice(null);
    try {
      const nextClient = client();
      await nextClient.health();
      const [nextSummary, nextWorks, nextTaxonomy] = await Promise.all([
        nextClient.summary(),
        nextClient.listWorks({
          query: "",
          status: "",
          seed: "all",
          limit: PAGE_SIZE,
          offset: 0,
        }),
        nextClient.currentTaxonomy(),
      ]);
      sessionStorage.setItem(SESSION_API_KEY, nextClient.baseUrl);
      sessionStorage.setItem(SESSION_TOKEN_KEY, token.trim());
      setApiUrl(nextClient.baseUrl);
      setSummary(nextSummary);
      setWorks(nextWorks);
      setTaxonomy(nextTaxonomy);
      setQuery("");
      setStatus("");
      setSeedScope("all");
      setConnection("connected");
    } catch (cause) {
      setConnection("error");
      setConnectionError(messageFromError(cause));
    }
  }

  function disconnect() {
    sessionStorage.removeItem(SESSION_TOKEN_KEY);
    setToken("");
    setConnection("offline");
    setConnectionError(null);
    setSummary(null);
    setTaxonomy(null);
    setWorks(EMPTY_PAGE);
    setSelectedId(null);
    setDetail(null);
    setNotice(null);
  }

  async function selectWork(workId: string) {
    if (connection !== "connected") return;
    setSelectedId(workId);
    setLoadingDetail(true);
    setNotice(null);
    try {
      const nextDetail = await client().getWork(workId);
      setDetail(nextDetail);
      setEditorRevision((current) => current + 1);
    } catch (cause) {
      setDetail(null);
      setNotice({ kind: "error", message: messageFromError(cause) });
    } finally {
      setLoadingDetail(false);
    }
  }

  async function refreshSummary() {
    try {
      setSummary(await client().summary());
    } catch (cause) {
      setNotice({ kind: "error", message: messageFromError(cause) });
    }
  }

  async function saveMetadata(
    changes: WorkPatch,
    expectedUpdatedAt: string | null,
  ) {
    if (!detail) return;
    setSaving(true);
    setNotice(null);
    try {
      const nextDetail = await client().updateWork(
        detail.id,
        changes,
        expectedUpdatedAt,
      );
      setDetail(nextDetail);
      setEditorRevision((current) => current + 1);
      setNotice({ kind: "success", message: "元数据已保存，并已记录审计日志。" });
      await Promise.all([loadWorks(works.offset), refreshSummary()]);
    } catch (cause) {
      setNotice({ kind: "error", message: messageFromError(cause) });
    } finally {
      setSaving(false);
    }
  }

  async function addClassification(classification: {
    dimension: string;
    category: string;
    confidence: number;
  }) {
    if (!detail || !taxonomy) return;
    setSaving(true);
    setNotice(null);
    try {
      const nextDetail = await client().addManualClassification(
        detail.id,
        classification,
        updatedAtFromDetail(detail),
        taxonomy.version,
      );
      setDetail(nextDetail);
      setEditorRevision((current) => current + 1);
      setNotice({ kind: "success", message: "人工分类已添加。" });
      await refreshSummary();
    } catch (cause) {
      setNotice({ kind: "error", message: messageFromError(cause) });
    } finally {
      setSaving(false);
    }
  }

  async function deleteClassification(classification: AdminClassification) {
    if (!detail || classification.method !== "manual") return;
    setSaving(true);
    setNotice(null);
    try {
      const nextDetail = await client().deleteManualClassification(
        detail.id,
        classification,
        updatedAtFromDetail(detail),
      );
      setDetail(nextDetail);
      setEditorRevision((current) => current + 1);
      setNotice({ kind: "success", message: "人工分类已删除。" });
      await refreshSummary();
    } catch (cause) {
      setNotice({ kind: "error", message: messageFromError(cause) });
    } finally {
      setSaving(false);
    }
  }

  const connected = connection === "connected";

  return (
    <main className="admin-app">
      <header className="admin-topbar">
        <div className="admin-brand">
          <div className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div>
            <p>NEUTRAL ATOM KNOWLEDGE BASE</p>
            <h1>数据库管理台</h1>
          </div>
        </div>
        <div className="admin-topbar-actions">
          <span className="write-safety-label">
            <ShieldCheck size={14} /> Loopback-only writes
          </span>
          <a className="back-to-atlas" href={publicUrl("/")}>
            <ArrowLeft size={15} /> 返回文献星图
          </a>
        </div>
      </header>

      <div className="admin-shell">
        <section className="admin-intro">
          <div>
            <span className="admin-kicker">CURATION WORKSPACE</span>
            <h2>校对原始记录，而不破坏引用网络</h2>
            <p>
              受控维护作品元数据与人工分类；identifier、seed、引用边和文档关联保持只读，所有写入均经过本地 API、版本检查、备份与审计。
            </p>
          </div>
          <div className="intro-status">
            <span className={connected ? "is-online" : ""} />
            {connected ? "Local database online" : "Static snapshot / offline"}
          </div>
        </section>

        <div className="admin-summary-grid">
          <SummaryCard icon={Database} label="作品记录" value={summary?.works ?? null} accent />
          <SummaryCard icon={BookOpen} label="核心 Bib 文献" value={summary?.seedWorks ?? null} />
          <SummaryCard icon={GitBranch} label="引用关系" value={summary?.citationEdges ?? null} />
          <SummaryCard icon={FileWarning} label="待解析 seed" value={summary?.unresolvedSeeds ?? null} />
          <SummaryCard icon={Tags} label="人工分类" value={summary?.manualClassifications ?? null} />
        </div>

        <div className="admin-main-grid">
          <aside className="admin-control-column">
            <ConnectionPanel
              apiUrl={apiUrl}
              error={connectionError}
              mode={mode}
              onApiUrlChange={setApiUrl}
              onConnect={() => void connect()}
              onDisconnect={disconnect}
              onTokenChange={setToken}
              state={connection}
              token={token}
            />
            <section className="admin-card safety-card">
              <div className="admin-card-heading">
                <div>
                  <span className="admin-kicker">WRITE BOUNDARY</span>
                  <h2>安全边界</h2>
                </div>
              </div>
              <ul>
                <li><span>可写</span> 标题、摘要、作者、日期、来源、URL、状态</li>
                <li><span>可写</span> method=manual 的分类</li>
                <li><strong>只读</strong> DOI / arXiv / OpenAlex identifiers</li>
                <li><strong>只读</strong> seed、引用边、provider topics、documents</li>
              </ul>
            </section>
          </aside>

          <div className="admin-data-column">
            <WorkTable
              connected={connected}
              items={works.items}
              limit={works.limit || PAGE_SIZE}
              loading={loadingWorks}
              offset={works.offset}
              onPageChange={(offset) => void loadWorks(offset)}
              onQueryChange={setQuery}
              onSearch={() => void loadWorks(0)}
              onSeedScopeChange={setSeedScope}
              onSelect={(workId) => void selectWork(workId)}
              onStatusChange={setStatus}
              query={query}
              seedScope={seedScope}
              selectedId={selectedId}
              status={status}
              total={works.total}
            />

            {loadingDetail && (
              <section className="admin-card record-placeholder" role="status">
                <LoaderCircle className="spin" size={24} /> 正在载入完整记录…
              </section>
            )}
            {!loadingDetail && detail && (
              <RecordEditor
                detail={detail}
                key={`${detail.id}-${editorRevision}`}
                notice={notice}
                onAddClassification={addClassification}
                onDeleteClassification={deleteClassification}
                onReload={() => void selectWork(detail.id)}
                onSave={saveMetadata}
                readOnly={!connected}
                saving={saving}
                taxonomy={taxonomy}
              />
            )}
            {!loadingDetail && connected && !detail && (
              <section className="admin-card record-placeholder">
                <RefreshCw size={22} />
                <div>
                  <strong>选择一条文献记录开始校对</strong>
                  <p>详情会显示可编辑元数据、人工分类和只读关系数据。</p>
                </div>
              </section>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
