import {
  ChevronLeft,
  ChevronRight,
  FileQuestion,
  LoaderCircle,
  Search,
} from "lucide-react";
import type { WorkListItem } from "./admin-api";

type Props = {
  connected: boolean;
  items: WorkListItem[];
  total: number;
  limit: number;
  offset: number;
  loading: boolean;
  query: string;
  status: string;
  seedScope: "all" | "seed" | "reference";
  selectedId: string | null;
  onQueryChange: (value: string) => void;
  onStatusChange: (value: string) => void;
  onSeedScopeChange: (value: "all" | "seed" | "reference") => void;
  onSearch: () => void;
  onPageChange: (offset: number) => void;
  onSelect: (workId: string) => void;
};

const STATUS_LABELS: Record<string, string> = {
  complete: "完整",
  unresolved_reference: "待解析引用",
  non_bibliographic: "非书目记录",
  unknown: "未知",
};

function authorPreview(authors: string[]): string {
  if (!authors.length) return "作者未知";
  if (authors.length <= 2) return authors.join(" · ");
  return `${authors.slice(0, 2).join(" · ")} 等`;
}

export default function WorkTable({
  connected,
  items,
  total,
  limit,
  offset,
  loading,
  query,
  status,
  seedScope,
  selectedId,
  onQueryChange,
  onStatusChange,
  onSeedScopeChange,
  onSearch,
  onPageChange,
  onSelect,
}: Props) {
  const start = total ? offset + 1 : 0;
  const end = Math.min(offset + items.length, total);
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));

  return (
    <section className="admin-card works-card" aria-labelledby="works-title">
      <div className="admin-card-heading works-heading">
        <div>
          <span className="admin-kicker">SOURCE RECORDS</span>
          <h2 id="works-title">文献记录</h2>
        </div>
        <span className="record-count">{total.toLocaleString("zh-CN")} records</span>
      </div>

      <form
        className="work-search-form"
        onSubmit={(event) => {
          event.preventDefault();
          onSearch();
        }}
      >
        <label className="work-search-input">
          <span className="sr-only">搜索文献记录</span>
          <Search aria-hidden="true" size={16} />
          <input
            autoComplete="off"
            disabled={!connected}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="标题、作者、DOI、OpenAlex ID…"
            type="search"
            value={query}
          />
        </label>
        <label>
          <span className="sr-only">元数据状态</span>
          <select
            disabled={!connected}
            onChange={(event) => onStatusChange(event.target.value)}
            value={status}
          >
            <option value="">全部状态</option>
            <option value="complete">完整</option>
            <option value="incomplete">信息不完整</option>
            <option value="unresolved_reference">待解析引用</option>
            <option value="no_title">缺少题名</option>
            <option value="non_bibliographic">非书目记录</option>
          </select>
        </label>
        <label>
          <span className="sr-only">记录范围</span>
          <select
            disabled={!connected}
            onChange={(event) =>
              onSeedScopeChange(event.target.value as Props["seedScope"])
            }
            value={seedScope}
          >
            <option value="all">全部记录</option>
            <option value="seed">核心 Bib 文献</option>
            <option value="reference">参考文献</option>
          </select>
        </label>
        <button className="admin-button is-secondary" disabled={!connected || loading}>
          {loading ? <LoaderCircle className="spin" size={15} /> : <Search size={15} />}
          检索
        </button>
      </form>

      <div className="work-table-scroll">
        <table className="work-table">
          <thead>
            <tr>
              <th scope="col">文献</th>
              <th scope="col">年份 / 来源</th>
              <th scope="col">状态</th>
              <th scope="col" aria-label="选择记录" />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr className={selectedId === item.id ? "is-selected" : ""} key={item.id}>
                <td>
                  <button
                    className="work-title-button"
                    onClick={() => onSelect(item.id)}
                    type="button"
                  >
                    <strong>{item.title}</strong>
                    <span>{authorPreview(item.authors)}</span>
                  </button>
                </td>
                <td>
                  <strong className="work-year">{item.year ?? "—"}</strong>
                  <span className="work-venue">{item.venue ?? item.doi ?? "来源未知"}</span>
                </td>
                <td>
                  <span className={`metadata-badge is-${item.metadataStatus}`}>
                    {STATUS_LABELS[item.metadataStatus] ?? item.metadataStatus}
                  </span>
                  {item.seed && <span className="seed-badge">SEED</span>}
                </td>
                <td>
                  <button
                    aria-label={`打开 ${item.title}`}
                    className="row-open-button"
                    onClick={() => onSelect(item.id)}
                    type="button"
                  >
                    <ChevronRight size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {!connected && (
          <div className="work-empty-state">
            <FileQuestion size={26} />
            <strong>连接本地数据库后显示原始记录</strong>
            <p>公开页面不会下载 SQLite 数据，也不会暴露管理凭据。</p>
          </div>
        )}
        {connected && !loading && !items.length && (
          <div className="work-empty-state">
            <Search size={26} />
            <strong>没有符合条件的记录</strong>
            <p>尝试缩短关键词或清除状态筛选。</p>
          </div>
        )}
        {loading && (
          <div className="work-loading-state" role="status">
            <LoaderCircle className="spin" size={23} />
            正在读取数据库…
          </div>
        )}
      </div>

      <footer className="table-pagination">
        <span>
          {start.toLocaleString("zh-CN")}—{end.toLocaleString("zh-CN")} / {total.toLocaleString("zh-CN")}
        </span>
        <div>
          <button
            aria-label="上一页"
            disabled={!connected || loading || offset === 0}
            onClick={() => onPageChange(Math.max(0, offset - limit))}
            type="button"
          >
            <ChevronLeft size={16} />
          </button>
          <span>{page} / {pages}</span>
          <button
            aria-label="下一页"
            disabled={!connected || loading || offset + limit >= total}
            onClick={() => onPageChange(offset + limit)}
            type="button"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </footer>
    </section>
  );
}
