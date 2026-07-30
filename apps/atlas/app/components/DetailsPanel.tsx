"use client";

import {
  ArrowDownLeft,
  ArrowUpRight,
  BookOpenText,
  Download,
  ExternalLink,
  GitCommitHorizontal,
  Languages,
  LoaderCircle,
  Network,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  authorLine,
  formatNumber,
  nodeDegree,
  safeExternalUrl,
} from "../graph-utils";
import { publicUrl } from "../site-config";
import type {
  ClassificationEvidence,
  GraphData,
  GraphNode,
  PaperClassificationDetail,
} from "../types";

type Props = {
  data: GraphData;
  isIsolatedRoot: boolean;
  selectedIndex: number | null;
  onClose: () => void;
  onFacetSelect: (dimensionId: string, categoryId: string) => void;
  onIsolate: (index: number) => void;
  onSelect: (index: number) => void;
};

type PaperLanguageCache = {
  titleZh?: string;
  abstract?: string;
  abstractZh?: string;
};

type TranslationAvailability =
  | "available"
  | "downloadable"
  | "downloading"
  | "unavailable";

type TranslatorSession = {
  translate: (input: string) => Promise<string>;
  destroy?: () => void;
};

type TranslatorFactory = {
  availability: (options: {
    sourceLanguage: string;
    targetLanguage: string;
  }) => Promise<TranslationAvailability>;
  create: (options: {
    sourceLanguage: string;
    targetLanguage: string;
    monitor?: (monitor: {
      addEventListener: (
        type: "downloadprogress",
        listener: (event: { loaded: number }) => void,
      ) => void;
    }) => void;
  }) => Promise<TranslatorSession>;
};

const CACHE_PREFIX = "neutral-atom-atlas:paper-language:v1:";

function readCache(nodeId: string): PaperLanguageCache {
  if (typeof window === "undefined") return {};
  try {
    const value = window.localStorage.getItem(`${CACHE_PREFIX}${nodeId}`);
    return value ? (JSON.parse(value) as PaperLanguageCache) : {};
  } catch {
    return {};
  }
}

function writeCache(nodeId: string, value: PaperLanguageCache) {
  try {
    window.localStorage.setItem(
      `${CACHE_PREFIX}${nodeId}`,
      JSON.stringify(value),
    );
  } catch {
    // Translation remains usable even if browser storage is unavailable.
  }
}

function getTranslatorFactory(): TranslatorFactory | null {
  const candidate = globalThis as typeof globalThis & {
    Translator?: TranslatorFactory;
  };
  return candidate.Translator ?? null;
}

function abstractFromInvertedIndex(
  inverted: Record<string, number[]> | null | undefined,
) {
  if (!inverted) return null;
  const words: [number, string][] = [];
  for (const [word, positions] of Object.entries(inverted)) {
    for (const position of positions) words.push([position, word]);
  }
  words.sort((left, right) => left[0] - right[0]);
  return words.map(([, word]) => word).join(" ").trim() || null;
}

function splitForTranslation(text: string, maxLength = 3200) {
  if (text.length <= maxLength) return [text];
  const sentences = text.match(/[^.!?。！？]+[.!?。！？]*/g) ?? [text];
  const chunks: string[] = [];
  let current = "";
  for (const sentence of sentences) {
    if (current && current.length + sentence.length > maxLength) {
      chunks.push(current.trim());
      current = "";
    }
    current += sentence;
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks;
}

async function translateLongText(
  translator: TranslatorSession,
  text: string,
) {
  const translated: string[] = [];
  for (const chunk of splitForTranslation(text)) {
    translated.push(await translator.translate(chunk));
  }
  return translated.join("\n");
}

export default function DetailsPanel({
  data,
  isIsolatedRoot,
  selectedIndex,
  onClose,
  onFacetSelect,
  onIsolate,
  onSelect,
}: Props) {
  const relations = useMemo(() => {
    if (selectedIndex == null) return { incoming: [], outgoing: [] };
    const incoming: number[] = [];
    const outgoing: number[] = [];
    for (const [source, target] of data.edges) {
      if (source === selectedIndex) outgoing.push(target);
      if (target === selectedIndex) incoming.push(source);
    }
    const rank = (left: number, right: number) =>
      nodeDegree(data.nodes[right]) - nodeDegree(data.nodes[left]);
    return {
      incoming: incoming.sort(rank),
      outgoing: outgoing.sort(rank),
    };
  }, [data, selectedIndex]);

  if (selectedIndex == null) return null;
  return (
    <PaperDetails
      data={data}
      isIsolatedRoot={isIsolatedRoot}
      key={data.nodes[selectedIndex].id}
      node={data.nodes[selectedIndex]}
      onClose={onClose}
      onFacetSelect={onFacetSelect}
      onIsolate={() => onIsolate(selectedIndex)}
      onSelect={onSelect}
      relations={relations}
    />
  );
}

function PaperDetails({
  data,
  isIsolatedRoot,
  node,
  onClose,
  onFacetSelect,
  onIsolate,
  onSelect,
  relations,
}: {
  data: GraphData;
  isIsolatedRoot: boolean;
  node: GraphNode;
  onClose: () => void;
  onFacetSelect: (dimensionId: string, categoryId: string) => void;
  onIsolate: () => void;
  onSelect: (index: number) => void;
  relations: { incoming: number[]; outgoing: number[] };
}) {
  const cached = useMemo(() => readCache(node.id), [node.id]);
  const [titleZh, setTitleZh] = useState(
    node.titleMissing ? "" : (cached.titleZh ?? ""),
  );
  const [abstract, setAbstract] = useState(
    node.titleMissing ? "" : (cached.abstract ?? node.abstract ?? ""),
  );
  const [abstractZh, setAbstractZh] = useState(cached.abstractZh ?? "");
  const [busy, setBusy] = useState<
    "title" | "abstract-load" | "abstract-translate" | null
  >(null);
  const [translationStatus, setTranslationStatus] = useState("");
  const [statusArea, setStatusArea] = useState<"title" | "abstract" | null>(
    null,
  );
  const translatorRef = useRef<TranslatorSession | null>(null);
  const [classificationDetail, setClassificationDetail] =
    useState<PaperClassificationDetail | null>(null);
  const [classificationLoading, setClassificationLoading] = useState(
    Boolean(node.classificationPath),
  );
  const [classificationError, setClassificationError] = useState("");

  useEffect(() => {
    if (!node.classificationPath) return;
    let cancelled = false;

    fetch(publicUrl(node.classificationPath))
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<PaperClassificationDetail>;
      })
      .then((payload) => {
        if (!cancelled) {
          setClassificationDetail({
            ...payload,
            facets: payload.facets ?? {},
            classifications: payload.classifications ?? [],
          });
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setClassificationError(
            cause instanceof Error ? cause.message : String(cause),
          );
        }
      })
      .finally(() => {
        if (!cancelled) setClassificationLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [node.classificationPath]);

  const section = data.sections.find(
    (item) => item.id === (node.layoutGroup ?? node.group),
  );
  const relationCount = relations.incoming.length + relations.outgoing.length;
  const externalUrl = node.titleMissing
    ? (node.doi ? safeExternalUrl(`https://doi.org/${node.doi}`) : null) ??
      safeExternalUrl(node.url)
    : safeExternalUrl(node.oaUrl) ??
      safeExternalUrl(node.url) ??
      (node.doi ? safeExternalUrl(`https://doi.org/${node.doi}`) : null);
  const openAlexUrl =
    !node.titleMissing && node.openalex
      ? `https://openalex.org/${node.openalex}`
      : null;

  function persist(patch: PaperLanguageCache) {
    writeCache(node.id, {
      titleZh,
      abstract,
      abstractZh,
      ...patch,
    });
  }

  async function ensureTranslator() {
    if (translatorRef.current) return translatorRef.current;
    const factory = getTranslatorFactory();
    if (!factory) {
      throw new Error(
        "当前浏览器不支持内置翻译，请使用桌面版 Chrome 138 或更高版本。",
      );
    }
    const options = { sourceLanguage: "en", targetLanguage: "zh" };
    const availability = await factory.availability(options);
    if (availability === "unavailable") {
      throw new Error("当前设备无法使用英文 → 中文语言包。");
    }
    if (availability !== "available") {
      setTranslationStatus("正在下载英文 → 中文翻译模型…");
    }
    const translator = await factory.create({
      ...options,
      monitor(monitor) {
        monitor.addEventListener("downloadprogress", (event) => {
          setTranslationStatus(
            `正在下载翻译模型 · ${Math.round(event.loaded * 100)}%`,
          );
        });
      },
    });
    translatorRef.current = translator;
    setTranslationStatus("本机翻译模型已就绪");
    return translator;
  }

  async function translateTitle() {
    setBusy("title");
    setStatusArea("title");
    setTranslationStatus("");
    try {
      const translator = await ensureTranslator();
      const translated = await translator.translate(node.title);
      setTitleZh(translated);
      persist({ titleZh: translated });
      setTranslationStatus("中文题目已缓存在当前浏览器");
    } catch (error) {
      setTranslationStatus(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setBusy(null);
    }
  }

  async function requestAbstract() {
    if (abstract) return abstract;
    if (node.titleMissing) {
      throw new Error("缺少可验证的书目信息，已跳过摘要请求。");
    }

    if (node.detailPath) {
      try {
        const detailResponse = await fetch(publicUrl(node.detailPath));
        if (detailResponse.ok) {
          const detail = (await detailResponse.json()) as {
            abstract?: string | null;
          };
          const localAbstract = detail.abstract?.trim();
          if (localAbstract) {
            setAbstract(localAbstract);
            persist({ abstract: localAbstract });
            return localAbstract;
          }
        }
      } catch {
        // Fall through to OpenAlex when the optional local shard is unavailable.
      }
    }

    if (!node.openalex) {
      throw new Error("该文献没有可用的本地摘要或 OpenAlex ID。");
    }
    const response = await fetch(
      `https://api.openalex.org/works/${encodeURIComponent(
        node.openalex,
      )}?select=id,abstract_inverted_index`,
    );
    if (!response.ok) throw new Error(`OpenAlex HTTP ${response.status}`);
    const payload = (await response.json()) as {
      abstract_inverted_index?: Record<string, number[]> | null;
    };
    const reconstructed = abstractFromInvertedIndex(
      payload.abstract_inverted_index,
    );
    if (!reconstructed) {
      throw new Error("OpenAlex 未收录该文献的摘要。");
    }
    setAbstract(reconstructed);
    persist({ abstract: reconstructed });
    return reconstructed;
  }

  async function loadAbstract() {
    setBusy("abstract-load");
    setStatusArea("abstract");
    setTranslationStatus("");
    try {
      await requestAbstract();
    } catch (error) {
      setTranslationStatus(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setBusy(null);
    }
  }

  async function translateAbstract() {
    setBusy("abstract-translate");
    setStatusArea("abstract");
    setTranslationStatus("");
    try {
      const translator = await ensureTranslator();
      const source = await requestAbstract();
      const translated = await translateLongText(translator, source);
      setAbstractZh(translated);
      persist({ abstract: source, abstractZh: translated });
      setTranslationStatus("中文摘要已缓存在当前浏览器");
    } catch (error) {
      setTranslationStatus(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <aside className="details-panel" aria-label="文献详情">
      <div className="details-header">
        <div className="details-label">
          <span
            className="legend-swatch"
            style={{ background: section?.color ?? "#7F8DA8" }}
          />
          <span>布局分区</span>
          <strong>{section?.label ?? "其他"}</strong>
        </div>
        <button
          aria-label="关闭详情"
          className="icon-button"
          onClick={onClose}
          title="关闭"
          type="button"
        >
          <X size={17} />
        </button>
      </div>

      <div className="details-scroll">
        <p className="details-year">{node.year ?? "年份未知"}</p>
        <h2>{node.title}</h2>
        {node.titleMissing ? (
          <p className="abstract-unavailable">
            {node.entityKind === "private_communication"
              ? "这是 BibTeX 中的 private communication 记录，不是可检索论文；因此不提供题目翻译或摘要请求。"
              : "上游元数据中没有可验证的标题。这里保留唯一标识和引用关系，不猜测或伪造题名。"}
          </p>
        ) : (
          <>
            {titleZh && <p className="translated-title">{titleZh}</p>}
            <button
              className="translate-button"
              disabled={busy != null}
              onClick={() => void translateTitle()}
              type="button"
            >
              {busy === "title" ? (
                <LoaderCircle className="spin" size={15} />
              ) : (
                <Languages size={15} />
              )}
              {titleZh ? "重新翻译题目" : "中文题目"}
            </button>
            {statusArea === "title" && translationStatus && (
              <p className="translation-status">{translationStatus}</p>
            )}
          </>
        )}

        <p className="details-authors">{authorLine(node.authors, 8)}</p>
        <p className="details-venue">{node.venue ?? "来源信息缺失"}</p>

        <div className="details-metrics">
          <div>
            <span>Graph degree</span>
            <strong>{formatNumber(nodeDegree(node))}</strong>
          </div>
          <div>
            <span>Cited by (OpenAlex)</span>
            <strong>{formatNumber(node.citations)}</strong>
          </div>
          <div>
            <span>References</span>
            <strong>{formatNumber(node.references)}</strong>
          </div>
        </div>

        {relationCount > 0 && (
          <button
            className="isolate-map-button"
            onClick={onIsolate}
            type="button"
          >
            <Network size={17} />
            <span>
              <strong>
                {isIsolatedRoot
                  ? "返回完整星图"
                  : "查看关联星图"}
              </strong>
              <small>
                {relationCount} 篇直接关联 · 可切换 1-hop / 2-hop
              </small>
            </span>
            <ArrowUpRight size={15} />
          </button>
        )}

        {(externalUrl || openAlexUrl) && (
          <div className="external-actions">
            {externalUrl && (
              <a href={externalUrl} rel="noreferrer" target="_blank">
                <BookOpenText size={16} />
                打开原始记录
                <ExternalLink size={14} />
              </a>
            )}
            {openAlexUrl && (
              <a href={openAlexUrl} rel="noreferrer" target="_blank">
                OpenAlex
                <ExternalLink size={14} />
              </a>
            )}
          </div>
        )}

        <ClassificationSection
          data={data}
          detail={classificationDetail}
          error={classificationError}
          loading={classificationLoading}
          node={node}
          onFacetSelect={onFacetSelect}
        />
        <section className="detail-section abstract-section">
          <div className="detail-section-title">
            <h3>Abstract</h3>
            {!node.titleMissing && abstract && (
              <button
                disabled={busy != null}
                onClick={() => void translateAbstract()}
                type="button"
              >
                {busy === "abstract-translate" ? (
                  <LoaderCircle className="spin" size={13} />
                ) : (
                  <Languages size={13} />
                )}
                {abstractZh ? "重新翻译" : "翻译摘要"}
              </button>
            )}
          </div>
          {node.titleMissing ? (
            <p className="abstract-unavailable">
              缺少可验证的书目信息，未发起摘要请求。
            </p>
          ) : abstract ? (
            <>
              <p className="abstract-original">{abstract}</p>
              {abstractZh && (
                <p className="abstract-translation">{abstractZh}</p>
              )}
            </>
          ) : node.detailPath || node.openalex ? (
            <button
              className="load-abstract-button"
              disabled={busy != null}
              onClick={() => void loadAbstract()}
              type="button"
            >
              {busy === "abstract-load" ? (
                <LoaderCircle className="spin" size={14} />
              ) : (
                <Download size={14} />
              )}
              {node.detailPath ? "加载本地摘要" : "从 OpenAlex 获取摘要"}
            </button>
          ) : (
            <p className="abstract-unavailable">没有可用的摘要来源。</p>
          )}
          {!node.titleMissing &&
            statusArea === "abstract" &&
            translationStatus && (
              <p className="translation-status">{translationStatus}</p>
            )}
        </section>

        {(node.doi ||
          node.arxiv ||
          node.openalex ||
          node.bibKey ||
          node.paperUid) && (
          <section className="detail-section">
            <h3>标识符</h3>
            <dl className="identifier-list">
              {node.paperUid && (
                <>
                  <dt>Database UID</dt>
                  <dd>{node.paperUid}</dd>
                </>
              )}
              <>
                <dt>Metadata</dt>
                <dd>{node.metadataStatus}</dd>
              </>
              {node.bibKey && (
                <>
                  <dt>BibTeX</dt>
                  <dd>{node.bibKey}</dd>
                </>
              )}
              {node.doi && (
                <>
                  <dt>DOI</dt>
                  <dd>{node.doi}</dd>
                </>
              )}
              {node.arxiv && (
                <>
                  <dt>arXiv</dt>
                  <dd>{node.arxiv}</dd>
                </>
              )}
              {node.openalex && (
                <>
                  <dt>OpenAlex</dt>
                  <dd>{node.openalex}</dd>
                </>
              )}
            </dl>
          </section>
        )}

        {node.topics.length > 0 && (
          <section className="detail-section">
            <h3>OpenAlex Topics</h3>
            <div className="topic-tags">
              {node.topics.map((topic) => (
                <span key={topic}>{topic}</span>
              ))}
            </div>
          </section>
        )}

        <RelationList
          data={data}
          icon={<ArrowDownLeft size={15} />}
          indices={relations.outgoing}
          label={`引用了 ${relations.outgoing.length} 篇`}
          onSelect={onSelect}
        />
        <RelationList
          data={data}
          icon={<ArrowUpRight size={15} />}
          indices={relations.incoming}
          label={`被 ${relations.incoming.length} 篇引用`}
          onSelect={onSelect}
        />
      </div>
    </aside>
  );
}

const METHOD_LABELS: Record<string, string> = {
  deterministic_rule: "规则匹配",
  review_hierarchy: "综述章节",
  venue_metadata: "Venue 元数据",
  manual: "人工确认",
};

function confidencePercent(value: number) {
  const normalized = value <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, Math.round(normalized)));
}

function ClassificationSection({
  data,
  detail,
  error,
  loading,
  node,
  onFacetSelect,
}: {
  data: GraphData;
  detail: PaperClassificationDetail | null;
  error: string;
  loading: boolean;
  node: GraphNode;
  onFacetSelect: (dimensionId: string, categoryId: string) => void;
}) {
  const dimensions = data.taxonomy?.dimensions ?? [];
  const dimensionById = new Map(
    dimensions.map((dimension, index) => [dimension.id, { dimension, index }]),
  );
  const evidenceByKey = new Map<string, ClassificationEvidence>();
  for (const evidence of detail?.classifications ?? []) {
    const key = `${evidence.dimension}:${evidence.category}`;
    const previous = evidenceByKey.get(key);
    if (!previous || evidence.confidence > previous.confidence) {
      evidenceByKey.set(key, evidence);
    }
  }

  const mergedFacets: Record<string, string[]> = { ...(detail?.facets ?? {}) };
  for (const [dimensionId, categoryIds] of Object.entries(node.facets ?? {})) {
    mergedFacets[dimensionId] = Array.from(
      new Set([...(mergedFacets[dimensionId] ?? []), ...categoryIds]),
    );
  }
  for (const evidence of detail?.classifications ?? []) {
    mergedFacets[evidence.dimension] = Array.from(
      new Set([
        ...(mergedFacets[evidence.dimension] ?? []),
        evidence.category,
      ]),
    );
  }

  const assignments = Object.entries(mergedFacets)
    .flatMap(([dimensionId, categoryIds]) =>
      categoryIds.map((categoryId) => {
        const dimensionEntry = dimensionById.get(dimensionId);
        const category = dimensionEntry?.dimension.categories.find(
          (item) => item.id === categoryId,
        );
        return {
          dimensionId,
          categoryId,
          dimensionIndex: dimensionEntry?.index ?? Number.MAX_SAFE_INTEGER,
          dimensionLabel:
            dimensionEntry?.dimension.label_zh ||
            dimensionEntry?.dimension.label_en ||
            dimensionId,
          categoryLabel:
            category?.label_zh || category?.label_en || categoryId,
          categoryLabelEn: category?.label_en,
          evidence: evidenceByKey.get(`${dimensionId}:${categoryId}`),
        };
      }),
    )
    .sort(
      (left, right) =>
        left.dimensionIndex - right.dimensionIndex ||
        left.categoryLabel.localeCompare(right.categoryLabel, "zh-CN"),
    );

  if (!assignments.length && !loading && !error) return null;

  return (
    <section className="detail-section classification-section">
      <div className="detail-section-title">
        <h3>分类与依据</h3>
        {data.taxonomy?.version && (
          <span className="taxonomy-version">{data.taxonomy.version}</span>
        )}
      </div>
      {loading && (
        <p className="classification-loading">
          <LoaderCircle className="spin" size={13} />
          正在加载公开分类依据…
        </p>
      )}
      {error && (
        <p className="classification-error">
          分类标签仍可使用，但依据 shard 加载失败：{error}
        </p>
      )}
      <div className="classification-list">
        {assignments.map((assignment) => {
          const evidence = assignment.evidence;
          const score = evidence
            ? confidencePercent(evidence.confidence)
            : null;
          return (
            <article
              className="classification-card"
              key={`${assignment.dimensionId}:${assignment.categoryId}`}
            >
              <div className="classification-card-heading">
                <div>
                  <small>{assignment.dimensionLabel}</small>
                  <button
                    onClick={() =>
                      onFacetSelect(
                        assignment.dimensionId,
                        assignment.categoryId,
                      )
                    }
                    title="将该分类加入左侧筛选"
                    type="button"
                  >
                    {assignment.categoryLabel}
                  </button>
                  {assignment.categoryLabelEn &&
                    assignment.categoryLabelEn !== assignment.categoryLabel && (
                      <span>{assignment.categoryLabelEn}</span>
                    )}
                </div>
                {score != null && <strong>{score}%</strong>}
              </div>

              {evidence ? (
                <details className="classification-evidence">
                  <summary>
                    {METHOD_LABELS[evidence.method] ?? evidence.method}
                    <span>查看依据</span>
                  </summary>
                  <div>
                    {evidence.signals.length > 0 && (
                      <section>
                        <h4>Signals</h4>
                        <ul>
                          {evidence.signals.map((signal, index) => (
                            <li key={`${signal.kind}:${signal.value}:${index}`}>
                              <span>{signal.field || signal.kind}</span>
                              <strong>{signal.value}</strong>
                            </li>
                          ))}
                        </ul>
                      </section>
                    )}
                    {evidence.review_sources.length > 0 && (
                      <section>
                        <h4>Review sources</h4>
                        <ul>
                          {evidence.review_sources.map((source) => (
                            <li key={source.mention_id}>
                              <span>{source.source_file}</span>
                              <strong>{source.heading}</strong>
                              <small>{source.mention_id}</small>
                            </li>
                          ))}
                        </ul>
                      </section>
                    )}
                    {evidence.rule_ids.length > 0 && (
                      <p className="classification-rules">
                        Rules: {evidence.rule_ids.join(" · ")}
                      </p>
                    )}
                  </div>
                </details>
              ) : (
                <p className="classification-no-evidence">
                  当前公开快照没有该标签的详细依据。
                </p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
function RelationList({
  data,
  indices,
  icon,
  label,
  onSelect,
}: {
  data: GraphData;
  indices: number[];
  icon: React.ReactNode;
  label: string;
  onSelect: (index: number) => void;
}) {
  if (!indices.length) return null;
  return (
    <section className="detail-section">
      <h3>
        <GitCommitHorizontal size={15} />
        {label}
      </h3>
      <div className="relation-list">
        {indices.slice(0, 10).map((index) => {
          const node = data.nodes[index];
          return (
            <button key={node.id} onClick={() => onSelect(index)} type="button">
              <span>{icon}</span>
              <span>
                <strong>{node.title}</strong>
                <small>{node.year ?? "年份未知"}</small>
              </span>
            </button>
          );
        })}
        {indices.length > 10 && (
          <p>另有 {indices.length - 10} 篇未在此处展开</p>
        )}
      </div>
    </section>
  );
}
