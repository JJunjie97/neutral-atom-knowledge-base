export type CitationDirection = "outgoing" | "incoming";
export type CitationFlowMode = "citation" | "development";

export const CITATION_FLOW_LABELS: Record<CitationFlowMode, string> = {
  citation: "引用者 → 被引用文献",
  development: "知识来源 → 后续工作",
};

export type CanvasPoint = {
  x: number;
  y: number;
};

export type OrientedCitationEdge = {
  from: number;
  to: number;
};

/**
 * Resolve the visual flow without changing the stored edge contract.
 *
 * - citation: source (citing work) -> target (cited work)
 * - development: target (knowledge source) -> source (later work)
 */
export function orientedCitationEdge(
  source: number,
  target: number,
  mode: CitationFlowMode,
): OrientedCitationEdge {
  return mode === "development"
    ? { from: target, to: source }
    : { from: source, to: target };
}

/**
 * Graph edges are stored as `citing work -> cited work`.
 *
 * Relative to the focused paper, `outgoing` means a reference used by the
 * focused paper; `incoming` means a later/other paper that cites it.
 */
export function citationDirectionForFocus(
  source: number,
  target: number,
  focusIndex: number,
): CitationDirection | null {
  if (source === focusIndex) return "outgoing";
  if (target === focusIndex) return "incoming";
  return null;
}

export function arrowheadPoints(
  from: CanvasPoint,
  to: CanvasPoint,
  options: {
    inset?: number;
    length?: number;
    halfWidth?: number;
  } = {},
): [CanvasPoint, CanvasPoint, CanvasPoint] | null {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const distance = Math.hypot(dx, dy);
  if (distance < 1) return null;

  const unitX = dx / distance;
  const unitY = dy / distance;
  const inset = Math.max(0, options.inset ?? 5);
  const length = Math.max(2, options.length ?? 7);
  const halfWidth = Math.max(1, options.halfWidth ?? 3.5);
  const tip = {
    x: to.x - unitX * inset,
    y: to.y - unitY * inset,
  };
  const base = {
    x: tip.x - unitX * length,
    y: tip.y - unitY * length,
  };

  return [
    tip,
    {
      x: base.x - unitY * halfWidth,
      y: base.y + unitX * halfWidth,
    },
    {
      x: base.x + unitY * halfWidth,
      y: base.y - unitX * halfWidth,
    },
  ];
}
