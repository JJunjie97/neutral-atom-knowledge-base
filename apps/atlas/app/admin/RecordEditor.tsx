"use client";

import {
  Braces,
  CheckCircle2,
  CircleAlert,
  FileJson,
  Fingerprint,
  Link2,
  ListTree,
  LoaderCircle,
  Plus,
  RefreshCw,
  Save,
  ShieldCheck,
  Tags,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import type {
  AdminClassification,
  AdminTaxonomy,
  JsonObject,
  WorkDetail,
  WorkPatch,
} from "./admin-api";
import {
  draftFromDetail,
  patchFromDraft,
  updatedAtFromDetail,
  type WorkDraft,
} from "./admin-types";

type EditorTab = "metadata" | "classifications" | "relations" | "json";

type Props = {
  detail: WorkDetail;
  taxonomy: AdminTaxonomy | null;
  readOnly: boolean;
  saving: boolean;
  notice: { kind: "success" | "error"; message: string } | null;
  onSave: (changes: WorkPatch, expectedUpdatedAt: string | null) => Promise<void>;
  onReload: () => void;
  onAddClassification: (classification: {
    dimension: string;
    category: string;
    confidence: number;
  }) => Promise<void>;
  onDeleteClassification: (classification: AdminClassification) => Promise<void>;
};

const TABS: { id: EditorTab; label: string; icon: typeof FileJson }[] = [
  { id: "metadata", label: "可编辑元数据", icon: FileJson },
  { id: "classifications", label: "人工分类", icon: Tags },
  { id: "relations", label: "只读关系", icon: ListTree },
  { id: "json", label: "Raw JSON", icon: Braces },
];

function value(record: JsonObject, ...keys: string[]): unknown {
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null) return record[key];
  }
  return null;
}

function readable(valueToFormat: unknown): string {
  if (valueToFormat == null || valueToFormat === "") return "—";
  if (typeof valueToFormat === "string") return valueToFormat;
  return JSON.stringify(valueToFormat, null, 2);
}

function JsonBlock({ value: blockValue }: { value: unknown }) {
  return <pre className="raw-json-block">{JSON.stringify(blockValue, null, 2)}</pre>;
}

export default function RecordEditor({
  detail,
  taxonomy,
  readOnly,
  saving,
  notice,
  onSave,
  onReload,
  onAddClassification,
  onDeleteClassification,
}: Props) {
  const [tab, setTab] = useState<EditorTab>("metadata");
  const [draft, setDraft] = useState<WorkDraft>(() => draftFromDetail(detail));
  const [draftError, setDraftError] = useState<string | null>(null);
  const [dimension, setDimension] = useState("");
  const [category, setCategory] = useState("");
  const [confidence, setConfidence] = useState("1");
  const updatedAt = updatedAtFromDetail(detail);
  const workTitle = readable(value(detail.work, "title", "display_name"));
  const topics = value(detail.work, "topics_json", "topics");
  const selectedDimension = taxonomy?.dimensions.find(
    (item) => item.id === dimension,
  );

  function updateDraft<Key extends keyof WorkDraft>(key: Key, next: WorkDraft[Key]) {
    setDraft((current) => ({ ...current, [key]: next }));
    setDraftError(null);
  }

  async function submitMetadata(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const changes = patchFromDraft(draft);
      setDraftError(null);
      await onSave(changes, updatedAt);
    } catch (cause) {
      setDraftError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function submitClassification(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const score = Number(confidence);
    if (!dimension.trim() || !category.trim()) {
      setDraftError("Dimension 与 category 均不能为空。");
      return;
    }
    if (!Number.isFinite(score) || score < 0 || score > 1) {
      setDraftError("Confidence 必须在 0—1 之间。");
      return;
    }
    setDraftError(null);
    await onAddClassification({
      dimension: dimension.trim(),
      category: category.trim(),
      confidence: score,
    });
    setDimension("");
    setCategory("");
    setConfidence("1");
  }

  return (
    <section className="admin-card record-editor" aria-labelledby="record-editor-title">
      <header className="record-editor-header">
        <div>
          <span className="admin-kicker">RECORD INSPECTOR</span>
          <h2 id="record-editor-title">{workTitle}</h2>
          <p>
            <code>{detail.id}</code>
            {updatedAt && <span>版本 {new Date(updatedAt).toLocaleString("zh-CN")}</span>}
          </p>
        </div>
        <button
          aria-label="重新载入记录"
          className="icon-action-button"
          disabled={saving}
          onClick={onReload}
          type="button"
        >
          <RefreshCw size={16} />
        </button>
      </header>

      <nav className="record-tabs" aria-label="记录详情分区">
        {TABS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              aria-current={tab === item.id ? "page" : undefined}
              className={tab === item.id ? "is-active" : ""}
              key={item.id}
              onClick={() => {
                setTab(item.id);
                setDraftError(null);
              }}
              type="button"
            >
              <Icon size={15} /> {item.label}
            </button>
          );
        })}
      </nav>

      {(notice || draftError) && (
        <div
          className={`editor-notice is-${draftError || notice?.kind === "error" ? "error" : "success"}`}
          role="status"
        >
          {draftError || notice?.kind === "error" ? (
            <CircleAlert size={16} />
          ) : (
            <CheckCircle2 size={16} />
          )}
          {draftError ?? notice?.message}
        </div>
      )}

      {tab === "metadata" && (
        <form className="metadata-form" onSubmit={(event) => void submitMetadata(event)}>
          <div className="edit-scope-note">
            <ShieldCheck size={17} />
            <p>
              此处只更新作品自身元数据。Identifier、引用边、seed 记录与文档索引由专用流程维护，不能在此修改。
            </p>
          </div>
          <label className="field-span-two">
            <span>标题</span>
            <input
              disabled={readOnly || saving}
              onChange={(event) => updateDraft("title", event.target.value)}
              value={draft.title}
            />
          </label>
          <label className="field-span-two">
            <span>摘要</span>
            <textarea
              className="abstract-field"
              disabled={readOnly || saving}
              onChange={(event) => updateDraft("abstract", event.target.value)}
              placeholder="原文摘要；翻译文本后续由独立字段管理。"
              value={draft.abstract}
            />
          </label>
          <label>
            <span>发表年份</span>
            <input
              disabled={readOnly || saving}
              inputMode="numeric"
              onChange={(event) => updateDraft("year", event.target.value)}
              placeholder="2025"
              value={draft.year}
            />
          </label>
          <label>
            <span>发表日期</span>
            <input
              disabled={readOnly || saving}
              onChange={(event) => updateDraft("publicationDate", event.target.value)}
              placeholder="YYYY-MM-DD"
              value={draft.publicationDate}
            />
          </label>
          <label>
            <span>Venue / Journal</span>
            <input
              disabled={readOnly || saving}
              onChange={(event) => updateDraft("venue", event.target.value)}
              value={draft.venue}
            />
          </label>
          <label>
            <span>Work type</span>
            <input
              disabled={readOnly || saving}
              onChange={(event) => updateDraft("workType", event.target.value)}
              placeholder="article / preprint / book-chapter"
              value={draft.workType}
            />
          </label>
          <label className="field-span-two">
            <span>作者（每行一位）</span>
            <textarea
              disabled={readOnly || saving}
              onChange={(event) => updateDraft("authors", event.target.value)}
              rows={4}
              value={draft.authors}
            />
          </label>
          <label>
            <span>Landing URL</span>
            <input
              disabled={readOnly || saving}
              inputMode="url"
              onChange={(event) => updateDraft("url", event.target.value)}
              value={draft.url}
            />
          </label>
          <label>
            <span>Open access URL</span>
            <input
              disabled={readOnly || saving}
              inputMode="url"
              onChange={(event) => updateDraft("oaUrl", event.target.value)}
              value={draft.oaUrl}
            />
          </label>
          <label>
            <span>元数据状态</span>
            <select
              disabled={readOnly || saving}
              onChange={(event) => updateDraft("metadataStatus", event.target.value)}
              value={draft.metadataStatus}
            >
              <option value="complete">完整 · complete</option>
              <option value="incomplete">信息不完整 · incomplete</option>
              <option value="unresolved_reference">待解析引用 · unresolved_reference</option>
              <option value="no_title">缺少题名 · no_title</option>
              <option value="non_bibliographic">非书目记录 · non_bibliographic</option>
            </select>
            <small>状态使用数据库枚举，不接受自由拼写。</small>
          </label>

          <div className="read-only-facts field-span-two">
            <div>
              <span>Entity kind</span>
              <strong>{readable(value(detail.work, "entity_kind"))}</strong>
            </div>
            <div>
              <span>Title source</span>
              <strong>{readable(value(detail.work, "title_source"))}</strong>
            </div>
          </div>

          <footer className="editor-actions field-span-two">
            <span>{readOnly ? "当前页面为只读模式" : "保存前会自动创建数据库备份并写入审计日志"}</span>
            <button
              className="admin-button is-primary"
              disabled={readOnly || saving}
              type="submit"
            >
              {saving ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}
              保存元数据
            </button>
          </footer>
        </form>
      )}

      {tab === "classifications" && (
        <div className="classification-editor">
          <div className="edit-scope-note">
            <Tags size={17} />
            <p>
              自动分类保留为证据；这里只能新增或删除 method=manual 的人工分类。
              {taxonomy ? ` 当前 taxonomy：${taxonomy.version}` : " 当前 taxonomy 未载入。"}
            </p>
          </div>
          <div className="classification-list">
            {detail.classifications.map((classification, index) => (
              <div className="classification-row" key={`${classification.id ?? index}`}>
                <div>
                  <strong>{classification.dimension}</strong>
                  <span>{classification.category}</span>
                </div>
                <div>
                  <span className={`method-badge is-${classification.method}`}>
                    {classification.method}
                  </span>
                  {classification.confidence != null && (
                    <small>{classification.confidence.toFixed(2)}</small>
                  )}
                  <button
                    aria-label={`删除人工分类 ${classification.category}`}
                    disabled={readOnly || saving || classification.method !== "manual"}
                    onClick={() => void onDeleteClassification(classification)}
                    title={classification.method === "manual" ? "删除人工分类" : "自动分类为只读"}
                    type="button"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            ))}
            {!detail.classifications.length && <p className="empty-copy">暂无分类记录。</p>}
          </div>
          <form
            className="classification-form"
            onSubmit={(event) => void submitClassification(event)}
          >
            <label>
              <span>分类维度</span>
              <select
                disabled={readOnly || saving}
                onChange={(event) => {
                  setDimension(event.target.value);
                  setCategory("");
                }}
                value={dimension}
              >
                <option value="">选择 dimension…</option>
                {taxonomy?.dimensions.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.labelZh || item.labelEn || item.id} · {item.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>分类类别</span>
              <select
                disabled={readOnly || saving || !selectedDimension}
                onChange={(event) => setCategory(event.target.value)}
                value={category}
              >
                <option value="">选择 category…</option>
                {selectedDimension?.categories.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.labelZh || item.labelEn || item.id} · {item.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Confidence</span>
              <input
                disabled={readOnly || saving}
                max="1"
                min="0"
                onChange={(event) => setConfidence(event.target.value)}
                step="0.05"
                type="number"
                value={confidence}
              />
            </label>
            <button
              className="admin-button is-primary"
              disabled={readOnly || saving || !taxonomy}
            >
              <Plus size={15} /> 添加 manual 分类
            </button>
          </form>
        </div>
      )}

      {tab === "relations" && (
        <div className="relations-view">
          <div className="readonly-banner">
            <Fingerprint size={18} />
            <div>
              <strong>关系数据只读</strong>
              <p>这些字段参与去重、canonical ID 与图结构计算，需使用专用导入/合并流程维护。</p>
            </div>
          </div>
          <section>
            <h3><Link2 size={16} /> Identifiers <span>{detail.identifiers.length}</span></h3>
            {detail.identifiers.length ? (
              <dl className="identifier-list">
                {detail.identifiers.map((identifier, index) => (
                  <div key={`${identifier.id ?? index}`}>
                    <dt>{identifier.scheme}</dt>
                    <dd>{identifier.value}</dd>
                  </div>
                ))}
              </dl>
            ) : <p className="empty-copy">无 identifier。</p>}
          </section>
          <section>
            <h3><ListTree size={16} /> Citation counts</h3>
            <JsonBlock value={detail.citationCounts} />
          </section>
          <section>
            <h3><Tags size={16} /> Provider topics</h3>
            <JsonBlock value={topics ?? []} />
          </section>
          <section>
            <h3>Seed records <span>{detail.seedEntries.length}</span></h3>
            <JsonBlock value={detail.seedEntries} />
          </section>
          <section>
            <h3>Documents <span>{detail.documents.length}</span></h3>
            <JsonBlock value={detail.documents} />
          </section>
        </div>
      )}

      {tab === "json" && (
        <div className="raw-json-view">
          <div className="readonly-banner">
            <Braces size={18} />
            <div>
              <strong>完整 API 响应 · 只读</strong>
              <p>用于审计与问题排查；此处不提供任意 JSON/SQL 写入。</p>
            </div>
          </div>
          <JsonBlock value={detail.raw} />
        </div>
      )}
    </section>
  );
}
