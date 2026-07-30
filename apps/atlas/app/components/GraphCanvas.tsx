"use client";

import {
  Focus,
  GitFork,
  Maximize2,
  Minus,
  Orbit,
  Plus,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  arrowheadPoints,
  CITATION_FLOW_LABELS,
  citationDirectionForFocus,
  orientedCitationEdge,
} from "../citation-direction";
import { nodeDegree } from "../graph-utils";
import { createTemporalCitationLayout } from "../temporal-citation-layout";
import type { GraphData, GraphLayoutMode } from "../types";

type Transform = {
  zoom: number;
  panX: number;
  panY: number;
};

type Point = {
  x: number;
  y: number;
};

type LocalGraph = {
  indices: number[];
  mask: Uint8Array;
  positions: Map<number, Point>;
  truncated: boolean;
};

type TemporalCanvasLayout = {
  positions: Map<number, Point>;
  layers: {
    year: number | null;
    kind: "year" | "unknown-year";
    label: string;
    x: number;
  }[];
  yearRange: { min: number; max: number } | null;
  edgeStats: {
    total: number;
    chronological: number;
    sameYear: number;
    reverseChronology: number;
    unknownYear: number;
    sourceCount: number;
  };
};

type Props = {
  data: GraphData;
  isolateDepth: 1 | 2;
  isolateRootIndex: number | null;
  layout: GraphLayoutMode;
  onLayoutChange: (layout: GraphLayoutMode) => void;
  onExitIsolate: () => void;
  onIsolateDepthChange: (depth: 1 | 2) => void;
  visibleIndices: number[];
  selectedIndex: number | null;
  onSelect: (index: number | null) => void;
};

const BACKGROUND = "#09101f";
const EDGE = "rgba(128, 151, 190, 0.12)";
const EDGE_FULL = "rgba(116, 139, 178, 0.065)";
const HIGHLIGHT = "#F5D67B";
const OUTGOING_EDGE = "#63DBC7";
const INCOMING_EDGE = "#FF8FA9";
const MAX_ZOOM = 256;
const MAX_LOCAL_NODES = 2800;

function publicationYearColor(
  year: number | null,
  range: { min: number; max: number } | null,
) {
  if (year == null || range == null) return "#7F8DA8";
  const span = Math.max(1, range.max - range.min);
  const ratio = Math.max(0, Math.min(1, (year - range.min) / span));
  const oldColor = [82, 194, 214];
  const newColor = [245, 214, 123];
  const channels = oldColor.map((start, index) =>
    Math.round(start + (newColor[index] - start) * ratio),
  );
  return `#${channels
    .map((channel) => channel.toString(16).padStart(2, "0"))
    .join("")}`;
}

export default function GraphCanvas({
  data,
  isolateDepth,
  isolateRootIndex,
  layout,
  onLayoutChange,
  onExitIsolate,
  onIsolateDepthChange,
  visibleIndices,
  selectedIndex,
  onSelect,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    pointerId: number;
    start: Point;
    origin: Point;
    moved: boolean;
  } | null>(null);
  const [size, setSize] = useState({ width: 900, height: 620 });
  const [transform, setTransform] = useState<Transform>({
    zoom: 0.96,
    panX: 0,
    panY: 0,
  });
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const colorMap = useMemo(
    () => new Map(data.sections.map((section) => [section.id, section.color])),
    [data.sections],
  );

  const visibleMask = useMemo(() => {
    const mask = new Uint8Array(data.nodes.length);
    for (const index of visibleIndices) mask[index] = 1;
    return mask;
  }, [data.nodes.length, visibleIndices]);

  const localGraph = useMemo<LocalGraph | null>(() => {
    if (isolateRootIndex == null) return null;

    const allowed = visibleMask.slice();
    allowed[isolateRootIndex] = 1;
    const adjacency = new Map<number, number[]>();
    for (const [source, target] of data.edges) {
      const sourceNeighbors = adjacency.get(source);
      if (sourceNeighbors) sourceNeighbors.push(target);
      else adjacency.set(source, [target]);
      const targetNeighbors = adjacency.get(target);
      if (targetNeighbors) targetNeighbors.push(source);
      else adjacency.set(target, [source]);
    }

    const depthByIndex = new Map<number, number>([[isolateRootIndex, 0]]);
    let frontier = [isolateRootIndex];
    let truncated = false;

    for (let depth = 1; depth <= isolateDepth; depth += 1) {
      const candidates = new Set<number>();
      for (const index of frontier) {
        for (const neighbor of adjacency.get(index) ?? []) {
          if (allowed[neighbor] && !depthByIndex.has(neighbor)) {
            candidates.add(neighbor);
          }
        }
      }

      let next = [...candidates].sort(
        (left, right) =>
          nodeDegree(data.nodes[right]) - nodeDegree(data.nodes[left]),
      );
      const remaining = MAX_LOCAL_NODES - depthByIndex.size;
      if (next.length > remaining) {
        next = next.slice(0, Math.max(remaining, 0));
        truncated = true;
      }
      for (const index of next) depthByIndex.set(index, depth);
      frontier = next;
      if (!frontier.length || depthByIndex.size >= MAX_LOCAL_NODES) break;
    }

    const groupOrder = new Map(
      data.sections.map((section, index) => [section.id, index]),
    );
    const positions = new Map<number, Point>([
      [isolateRootIndex, { x: 0, y: 0 }],
    ]);

    for (let depth = 1; depth <= isolateDepth; depth += 1) {
      const layer = [...depthByIndex.entries()]
        .filter(([, itemDepth]) => itemDepth === depth)
        .map(([index]) => index)
        .sort((left, right) => {
          const groupDiff =
            (groupOrder.get(data.nodes[left].group) ?? 99) -
            (groupOrder.get(data.nodes[right].group) ?? 99);
          if (groupDiff) return groupDiff;
          return nodeDegree(data.nodes[right]) - nodeDegree(data.nodes[left]);
        });

      layer.forEach((index, rank) => {
        const fraction = rank / Math.max(layer.length, 1);
        const angle = fraction * Math.PI * 2 - Math.PI / 2;
        const ripple = (rank % 5) / 5;
        const radius =
          depth === 1
            ? 0.48 + ripple * 0.18
            : 1.0 + Math.sqrt(fraction) * 0.42 + ripple * 0.08;
        positions.set(index, {
          x: Math.cos(angle) * radius,
          y: Math.sin(angle) * radius,
        });
      });
    }

    const indices = [...depthByIndex.keys()];
    const mask = new Uint8Array(data.nodes.length);
    for (const index of indices) mask[index] = 1;
    return { indices, mask, positions, truncated };
  }, [
    data.edges,
    data.nodes,
    data.sections,
    isolateDepth,
    isolateRootIndex,
    visibleMask,
  ]);

  const renderIndices = localGraph?.indices ?? visibleIndices;
  const renderMask = localGraph?.mask ?? visibleMask;
  const focusIndex = selectedIndex ?? hoveredIndex;

  const temporalLayout = useMemo<TemporalCanvasLayout | null>(() => {
    if (layout !== "lineage" || !renderIndices.length) return null;

    const localIndexByGlobal = new Map<number, number>();
    renderIndices.forEach((globalIndex, localIndex) => {
      localIndexByGlobal.set(globalIndex, localIndex);
    });
    const subNodes = renderIndices.map((index) => ({
      id: data.nodes[index].id,
      year: data.nodes[index].year,
    }));
    const subEdges: [number, number][] = [];
    const sourceIndices = new Set<number>();
    const edgeStats = {
      total: 0,
      chronological: 0,
      sameYear: 0,
      reverseChronology: 0,
      unknownYear: 0,
      sourceCount: 0,
    };

    for (const [source, target] of data.edges) {
      if (!renderMask[source] || !renderMask[target]) continue;
      const localSource = localIndexByGlobal.get(source);
      const localTarget = localIndexByGlobal.get(target);
      if (localSource == null || localTarget == null) continue;
      subEdges.push([localSource, localTarget]);
      sourceIndices.add(source);
      edgeStats.total += 1;
      const sourceYear = data.nodes[source].year;
      const targetYear = data.nodes[target].year;
      if (sourceYear == null || targetYear == null) {
        edgeStats.unknownYear += 1;
      } else if (sourceYear === targetYear) {
        edgeStats.sameYear += 1;
      } else if (sourceYear > targetYear) {
        edgeStats.chronological += 1;
      } else {
        edgeStats.reverseChronology += 1;
      }
    }
    edgeStats.sourceCount = sourceIndices.size;

    const raw = createTemporalCitationLayout(subNodes, subEdges, {
      yearGap: 1,
      nodeGap: 1,
      unknownYearGap: 1.4,
    });
    const centerX = (raw.bounds.minX + raw.bounds.maxX) / 2;
    const rootLocalIndex =
      isolateRootIndex == null
        ? null
        : (localIndexByGlobal.get(isolateRootIndex) ?? null);
    const centerY =
      rootLocalIndex == null
        ? (raw.bounds.minY + raw.bounds.maxY) / 2
        : raw.positions[rootLocalIndex].y;
    const xScale = 2.8 / Math.max(raw.bounds.width, 1);
    const yExtent = Math.max(
      0.5,
      ...raw.positions.map((position) => Math.abs(position.y - centerY)),
    );
    const yScale = 1.12 / yExtent;
    const positions = new Map<number, Point>();
    raw.positions.forEach((position, localIndex) => {
      positions.set(renderIndices[localIndex], {
        x: (position.x - centerX) * xScale,
        y: (position.y - centerY) * yScale,
      });
    });

    return {
      positions,
      layers: raw.layers.map((layer) => ({
        year: layer.year,
        kind: layer.kind,
        label: layer.label,
        x: (layer.x - centerX) * xScale,
      })),
      yearRange: raw.yearRange,
      edgeStats,
    };
  }, [
    data.edges,
    data.nodes,
    isolateRootIndex,
    layout,
    renderIndices,
    renderMask,
  ]);

  const directedEdgeKeys = useMemo(
    () => new Set(data.edges.map(([source, target]) => `${source}:${target}`)),
    [data.edges],
  );

  const focusRelationCounts = useMemo(() => {
    const counts = { outgoing: 0, incoming: 0 };
    if (focusIndex == null) return counts;
    for (const [source, target] of data.edges) {
      if (!renderMask[source] || !renderMask[target]) continue;
      const direction = citationDirectionForFocus(source, target, focusIndex);
      if (direction) counts[direction] += 1;
    }
    return counts;
  }, [data.edges, focusIndex, renderMask]);

  const positionFor = useCallback(
    (index: number): Point =>
      temporalLayout?.positions.get(index) ??
      localGraph?.positions.get(index) ?? {
        x: data.nodes[index].x,
        y: data.nodes[index].y,
      },
    [data.nodes, localGraph, temporalLayout],
  );

  const degreeLeaders = useMemo(
    () =>
      [...renderIndices]
        .sort(
          (left, right) =>
            nodeDegree(data.nodes[right]) - nodeDegree(data.nodes[left]),
        )
        .slice(0, renderIndices.length > 1000 ? 6 : 16),
    [data.nodes, renderIndices],
  );

  const baseScale = Math.min(size.width, size.height) * 0.38;

  const worldToScreen = useCallback(
    (x: number, y: number): Point => ({
      x: size.width / 2 + transform.panX + x * baseScale * transform.zoom,
      y: size.height / 2 + transform.panY + y * baseScale * transform.zoom,
    }),
    [baseScale, size.height, size.width, transform],
  );

  const screenToWorld = useCallback(
    (x: number, y: number): Point => ({
      x:
        (x - size.width / 2 - transform.panX) /
        (baseScale * transform.zoom),
      y:
        (y - size.height / 2 - transform.panY) /
        (baseScale * transform.zoom),
    }),
    [baseScale, size.height, size.width, transform],
  );

  const findNodeAt = useCallback(
    (screenX: number, screenY: number) => {
      const world = screenToWorld(screenX, screenY);
      const tolerance = 12 / (baseScale * transform.zoom);
      let nearest: number | null = null;
      let nearestDistance = tolerance * tolerance;

      for (const index of renderIndices) {
        const position = positionFor(index);
        const dx = position.x - world.x;
        const dy = position.y - world.y;
        const distance = dx * dx + dy * dy;
        if (distance < nearestDistance) {
          nearest = index;
          nearestDistance = distance;
        }
      }
      return nearest;
    },
    [
      baseScale,
      positionFor,
      renderIndices,
      screenToWorld,
      transform.zoom,
    ],
  );

  useEffect(() => {
    const shell = shellRef.current;
    if (!shell) return;
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.max(320, Math.floor(entry.contentRect.width));
      const height = Math.max(420, Math.floor(entry.contentRect.height));
      setSize({ width, height });
    });
    observer.observe(shell);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.floor(size.width * dpr);
    canvas.height = Math.floor(size.height * dpr);
    canvas.style.width = `${size.width}px`;
    canvas.style.height = `${size.height}px`;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);

    const frame = requestAnimationFrame(() => {
      context.fillStyle = BACKGROUND;
      context.fillRect(0, 0, size.width, size.height);

      if (temporalLayout) {
        const visibleLayers = temporalLayout.layers
          .map((layer) => ({
            ...layer,
            screenX: worldToScreen(layer.x, 0).x,
          }))
          .filter(
            (layer) => layer.screenX >= -30 && layer.screenX <= size.width + 30,
          )
          .sort((left, right) => left.screenX - right.screenX);
        let lastLabelX = Number.NEGATIVE_INFINITY;
        context.font =
          '500 10px "SFMono-Regular", Consolas, monospace';
        context.textBaseline = "top";
        for (const layer of visibleLayers) {
          context.beginPath();
          context.setLineDash(layer.kind === "unknown-year" ? [4, 5] : []);
          context.moveTo(layer.screenX, 0);
          context.lineTo(layer.screenX, size.height);
          context.strokeStyle =
            layer.kind === "unknown-year"
              ? "rgba(183, 172, 230, 0.24)"
              : "rgba(112, 142, 188, 0.14)";
          context.lineWidth = 0.75;
          context.stroke();
          if (
            layer.kind === "unknown-year" ||
            layer.screenX - lastLabelX >= 48
          ) {
            context.fillStyle =
              layer.kind === "unknown-year"
                ? "rgba(205, 198, 239, 0.78)"
                : "rgba(154, 174, 207, 0.66)";
            context.fillText(
              layer.kind === "unknown-year" ? "年份未知" : layer.label,
              layer.screenX + 4,
              8,
            );
            lastLabelX = layer.screenX;
          }
        }
        context.setLineDash([]);
      } else {
        context.fillStyle = "rgba(112, 142, 188, 0.16)";
        const grid = 44;
        const offsetX = ((transform.panX % grid) + grid) % grid;
        const offsetY = ((transform.panY % grid) + grid) % grid;
        for (let x = offsetX; x < size.width; x += grid) {
          for (let y = offsetY; y < size.height; y += grid) {
            context.fillRect(x, y, 1, 1);
          }
        }
      }

      const focusNeighbors = new Set<number>();
      if (focusIndex != null) {
        focusNeighbors.add(focusIndex);
        for (const [source, target] of data.edges) {
          if (source === focusIndex) focusNeighbors.add(target);
          if (target === focusIndex) focusNeighbors.add(source);
        }
      }

      const nodeRadiusFor = (index: number) => {
        const node = data.nodes[index];
        const baseRadius =
          data.nodes.length > 1000 && !node.seed && localGraph == null
            ? 1.15
            : Math.min(8.5, 2.1 + Math.sqrt(nodeDegree(node) + 1) * 0.34);
        return index === isolateRootIndex || index === focusIndex
          ? Math.max(7, baseRadius + 2.7)
          : baseRadius;
      };

      const drawAllEdges =
        localGraph != null ||
        data.nodes.length <= 1000 ||
        transform.zoom > 1.18 ||
        focusIndex != null;
      if (drawAllEdges) {
        const drawBackgroundEdges = (
          edgeKind: "all" | "regular" | "unknown-year" | "reverse-year",
          strokeStyle: string,
          dash: number[] = [],
        ) => {
          context.beginPath();
          for (const [source, target] of data.edges) {
            if (!renderMask[source] || !renderMask[target]) continue;
            if (
              focusIndex != null &&
              (source === focusIndex || target === focusIndex)
            ) {
              continue;
            }
            const sourceYear = data.nodes[source].year;
            const targetYear = data.nodes[target].year;
            const unknownYear = sourceYear == null || targetYear == null;
            const reverseYear =
              sourceYear != null &&
              targetYear != null &&
              sourceYear < targetYear;
            if (edgeKind === "regular" && (unknownYear || reverseYear)) continue;
            if (edgeKind === "unknown-year" && !unknownYear) continue;
            if (edgeKind === "reverse-year" && !reverseYear) continue;

            const visualEdge = orientedCitationEdge(
              source,
              target,
              temporalLayout ? "development" : "citation",
            );
            const fromPosition = positionFor(visualEdge.from);
            const toPosition = positionFor(visualEdge.to);
            const from = worldToScreen(fromPosition.x, fromPosition.y);
            const to = worldToScreen(toPosition.x, toPosition.y);
            context.moveTo(from.x, from.y);
            context.lineTo(to.x, to.y);
          }
          context.setLineDash(dash);
          context.strokeStyle = strokeStyle;
          context.lineWidth = 0.65;
          context.stroke();
          context.setLineDash([]);
        };

        if (temporalLayout) {
          drawBackgroundEdges("regular", "rgba(106, 176, 191, 0.13)");
          drawBackgroundEdges(
            "unknown-year",
            "rgba(164, 157, 203, 0.14)",
            [2, 4],
          );
          drawBackgroundEdges(
            "reverse-year",
            "rgba(255, 143, 169, 0.25)",
            [5, 4],
          );
        } else {
          drawBackgroundEdges(
            "all",
            data.nodes.length > 1000 && localGraph == null ? EDGE_FULL : EDGE,
          );
        }

        const showDevelopmentArrowheads =
          temporalLayout != null &&
          (temporalLayout.edgeStats.total <= 1500 ||
            (transform.zoom > 2.6 && temporalLayout.edgeStats.total <= 5000));
        if (showDevelopmentArrowheads) {
          for (const [source, target] of data.edges) {
            if (!renderMask[source] || !renderMask[target]) continue;
            if (
              focusIndex != null &&
              (source === focusIndex || target === focusIndex)
            ) {
              continue;
            }
            const visualEdge = orientedCitationEdge(
              source,
              target,
              "development",
            );
            const fromPosition = positionFor(visualEdge.from);
            const toPosition = positionFor(visualEdge.to);
            const from = worldToScreen(fromPosition.x, fromPosition.y);
            const to = worldToScreen(toPosition.x, toPosition.y);
            if (
              (from.x < -30 && to.x < -30) ||
              (from.x > size.width + 30 && to.x > size.width + 30) ||
              (from.y < -30 && to.y < -30) ||
              (from.y > size.height + 30 && to.y > size.height + 30)
            ) {
              continue;
            }
            const arrowhead = arrowheadPoints(from, to, {
              inset: nodeRadiusFor(visualEdge.to) + 1.5,
              length: 5,
              halfWidth: 2.5,
            });
            if (!arrowhead) continue;
            const sourceYear = data.nodes[source].year;
            const targetYear = data.nodes[target].year;
            const reverseYear =
              sourceYear != null &&
              targetYear != null &&
              sourceYear < targetYear;
            context.beginPath();
            context.moveTo(arrowhead[0].x, arrowhead[0].y);
            context.lineTo(arrowhead[1].x, arrowhead[1].y);
            context.lineTo(arrowhead[2].x, arrowhead[2].y);
            context.closePath();
            context.fillStyle = reverseYear
              ? "rgba(255, 143, 169, 0.48)"
              : "rgba(112, 192, 200, 0.38)";
            context.fill();
          }
        }
      }

      if (focusIndex != null) {
        for (const [source, target] of data.edges) {
          if (!renderMask[source] || !renderMask[target]) continue;
          const direction = citationDirectionForFocus(
            source,
            target,
            focusIndex,
          );
          if (!direction) continue;

          const visualEdge = orientedCitationEdge(
            source,
            target,
            temporalLayout ? "development" : "citation",
          );
          const fromPosition = positionFor(visualEdge.from);
          const toPosition = positionFor(visualEdge.to);
          const from = worldToScreen(fromPosition.x, fromPosition.y);
          const to = worldToScreen(toPosition.x, toPosition.y);
          const dx = to.x - from.x;
          const dy = to.y - from.y;
          const distance = Math.hypot(dx, dy);
          if (distance < 1) continue;

          const isReciprocal = directedEdgeKeys.has(`${target}:${source}`);
          const sameYear =
            data.nodes[source].year != null &&
            data.nodes[source].year === data.nodes[target].year;
          const curveOffset = isReciprocal
            ? Math.min(18, Math.max(8, distance * 0.08))
            : temporalLayout && sameYear
              ? Math.min(14, Math.max(6, distance * 0.06))
              : 0;
          const control = {
            x: (from.x + to.x) / 2 - (dy / distance) * curveOffset,
            y: (from.y + to.y) / 2 + (dx / distance) * curveOffset,
          };
          const color =
            direction === "outgoing" ? OUTGOING_EDGE : INCOMING_EDGE;

          context.beginPath();
          context.moveTo(from.x, from.y);
          context.quadraticCurveTo(control.x, control.y, to.x, to.y);
          context.strokeStyle = color;
          context.lineWidth = 1.4;
          context.stroke();

          const arrowhead = arrowheadPoints(control, to, {
            inset: nodeRadiusFor(visualEdge.to) + 2,
            length: 7,
            halfWidth: 3.5,
          });
          if (arrowhead && distance > 14) {
            context.beginPath();
            context.moveTo(arrowhead[0].x, arrowhead[0].y);
            context.lineTo(arrowhead[1].x, arrowhead[1].y);
            context.lineTo(arrowhead[2].x, arrowhead[2].y);
            context.closePath();
            context.fillStyle = color;
            context.fill();
          }
        }
      }

      for (const index of renderIndices) {
        const node = data.nodes[index];
        const position = positionFor(index);
        const point = worldToScreen(position.x, position.y);
        if (
          point.x < -20 ||
          point.y < -20 ||
          point.x > size.width + 20 ||
          point.y > size.height + 20
        ) {
          continue;
        }
        const isFocus = index === focusIndex;
        const isRoot = index === isolateRootIndex;
        const isNeighbor = focusNeighbors.has(index);
        const radius = nodeRadiusFor(index);
        const color = temporalLayout
          ? publicationYearColor(node.year, temporalLayout.yearRange)
          : (colorMap.get(node.group) ?? "#7F8DA8");

        if (isRoot || isFocus) {
          context.beginPath();
          context.arc(point.x, point.y, radius + 5, 0, Math.PI * 2);
          context.fillStyle = isRoot
            ? "rgba(99, 219, 199, 0.18)"
            : "rgba(245, 214, 123, 0.16)";
          context.fill();
        }

        context.beginPath();
        context.arc(point.x, point.y, radius, 0, Math.PI * 2);
        context.fillStyle =
          focusIndex != null && !isNeighbor && !isRoot ? `${color}40` : color;
        context.fill();
        if (node.seed || isRoot) {
          context.strokeStyle = isRoot
            ? "#63DBC7"
            : isFocus
              ? HIGHLIGHT
              : "rgba(255, 255, 255, 0.42)";
          context.lineWidth = isRoot || isFocus ? 1.8 : 0.65;
          context.stroke();
        }
      }

      const labels = new Set<number>();
      if (
        transform.zoom > 1.12 &&
        (renderIndices.length <= 1000 || localGraph != null)
      ) {
        degreeLeaders.forEach((index) => labels.add(index));
      }
      if (hoveredIndex != null) labels.add(hoveredIndex);
      if (selectedIndex != null) labels.add(selectedIndex);
      if (isolateRootIndex != null) labels.add(isolateRootIndex);

      context.font =
        '500 12px ui-sans-serif, "Microsoft YaHei", system-ui, sans-serif';
      context.textBaseline = "middle";
      for (const index of labels) {
        if (!renderMask[index]) continue;
        const node = data.nodes[index];
        const position = positionFor(index);
        const point = worldToScreen(position.x, position.y);
        const rawTitle = temporalLayout
          ? `${node.year ?? "年份未知"} · ${node.title}`
          : node.title;
        const title =
          rawTitle.length > 52 ? `${rawTitle.slice(0, 52)}…` : rawTitle;
        const width = context.measureText(title).width;
        const labelX = point.x + 11;
        const labelY = point.y;
        context.fillStyle = "rgba(5, 11, 23, 0.9)";
        context.fillRect(labelX - 5, labelY - 11, width + 10, 22);
        context.fillStyle =
          index === isolateRootIndex
            ? "#63DBC7"
            : index === selectedIndex
              ? HIGHLIGHT
              : "#E8EDF7";
        context.fillText(title, labelX, labelY);
      }
    });

    return () => cancelAnimationFrame(frame);
  }, [
    colorMap,
    data.edges,
    data.nodes,
    degreeLeaders,
    directedEdgeKeys,
    focusIndex,
    hoveredIndex,
    isolateRootIndex,
    localGraph,
    positionFor,
    renderIndices,
    renderMask,
    selectedIndex,
    size,
    temporalLayout,
    transform,
    worldToScreen,
  ]);

  const updateZoom = useCallback(
    (nextZoom: number, anchor: Point) => {
      const clamped = Math.max(0.12, Math.min(MAX_ZOOM, nextZoom));
      setTransform((current) => {
        const worldX =
          (anchor.x - size.width / 2 - current.panX) /
          (baseScale * current.zoom);
        const worldY =
          (anchor.y - size.height / 2 - current.panY) /
          (baseScale * current.zoom);
        return {
          zoom: clamped,
          panX: anchor.x - size.width / 2 - worldX * baseScale * clamped,
          panY: anchor.y - size.height / 2 - worldY * baseScale * clamped,
        };
      });
    },
    [baseScale, size.height, size.width],
  );

  const resetView = useCallback(() => {
    setTransform({ zoom: 0.96, panX: 0, panY: 0 });
  }, []);

  const focusSelected = useCallback(() => {
    if (selectedIndex == null) {
      resetView();
      return;
    }
    const position = positionFor(selectedIndex);
    setTransform({
      zoom: 3.2,
      panX: -position.x * baseScale * 3.2,
      panY: -position.y * baseScale * 3.2,
    });
  }, [baseScale, positionFor, resetView, selectedIndex]);

  const centerAnchor = {
    x: size.width / 2,
    y: size.height / 2,
  };

  return (
    <div className="graph-canvas-shell" ref={shellRef}>
      <canvas
        aria-label={
          temporalLayout
            ? `可交互文献发展脉络图；箭头方向为${CITATION_FLOW_LABELS.development}`
            : `可交互文献引用星图；箭头方向为${CITATION_FLOW_LABELS.citation}`
        }
        className="graph-canvas"
        onPointerDown={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect();
          dragRef.current = {
            pointerId: event.pointerId,
            start: {
              x: event.clientX - bounds.left,
              y: event.clientY - bounds.top,
            },
            origin: { x: transform.panX, y: transform.panY },
            moved: false,
          };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect();
          const point = {
            x: event.clientX - bounds.left,
            y: event.clientY - bounds.top,
          };
          const drag = dragRef.current;
          if (drag && drag.pointerId === event.pointerId) {
            const dx = point.x - drag.start.x;
            const dy = point.y - drag.start.y;
            if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
            setTransform((current) => ({
              ...current,
              panX: drag.origin.x + dx,
              panY: drag.origin.y + dy,
            }));
          } else {
            setHoveredIndex(findNodeAt(point.x, point.y));
          }
        }}
        onPointerUp={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect();
          const drag = dragRef.current;
          if (drag && !drag.moved) {
            onSelect(
              findNodeAt(
                event.clientX - bounds.left,
                event.clientY - bounds.top,
              ),
            );
          }
          dragRef.current = null;
          event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onPointerLeave={() => {
          if (!dragRef.current) setHoveredIndex(null);
        }}
        onWheel={(event) => {
          event.preventDefault();
          const bounds = event.currentTarget.getBoundingClientRect();
          const factor = Math.exp(-event.deltaY * 0.0016);
          updateZoom(transform.zoom * factor, {
            x: event.clientX - bounds.left,
            y: event.clientY - bounds.top,
          });
        }}
        ref={canvasRef}
      />

      <div className="graph-status" aria-live="polite">
        <span className="status-dot" />
        {localGraph ? (
          <>
            {temporalLayout ? "局部发展脉络" : "局部引用星图"} ·{" "}
            {renderIndices.length.toLocaleString("zh-CN")} 篇
            {localGraph.truncated ? " · 仅显示前 2,800 篇" : ""}
          </>
        ) : (
          <>
            {temporalLayout ? "发展脉络" : "关系星图"} ·{" "}
            {renderIndices.length.toLocaleString("zh-CN")} /{" "}
            {data.nodes.length.toLocaleString("zh-CN")} 篇文献
          </>
        )}
      </div>

      {temporalLayout ? (
        <div
          aria-label={`发展脉络图例：${CITATION_FLOW_LABELS.development}`}
          className={`citation-direction-legend lineage-legend ${
            localGraph ? "is-local" : ""
          }`}
          role="note"
        >
          <strong>发展流向 · {CITATION_FLOW_LABELS.development}</strong>
          <span className="lineage-explanation">
            原始引用边反向呈现为知识传播方向；年份从左向右增长。
          </span>
          {temporalLayout.yearRange && (
            <span className="lineage-year-scale">
              <span>{temporalLayout.yearRange.min}</span>
              <i aria-hidden="true" />
              <span>{temporalLayout.yearRange.max}</span>
            </span>
          )}
          {focusIndex != null && (
            <>
              <span className="direction-legend-row">
                <span
                  aria-hidden="true"
                  className="direction-legend-arrow is-outgoing"
                >
                  →
                </span>
                知识来源 → 当前文献（{focusRelationCounts.outgoing}）
              </span>
              <span className="direction-legend-row">
                <span
                  aria-hidden="true"
                  className="direction-legend-arrow is-incoming"
                >
                  →
                </span>
                当前文献 → 后续工作（{focusRelationCounts.incoming}）
              </span>
            </>
          )}
          <span className="lineage-edge-summary">
            同年关系 {temporalLayout.edgeStats.sameYear.toLocaleString("zh-CN")} ·{" "}
            年份反常 {temporalLayout.edgeStats.reverseChronology.toLocaleString("zh-CN")}（粉色虚线） ·{" "}
            年份未知 {temporalLayout.edgeStats.unknownYear.toLocaleString("zh-CN")}
          </span>
          <span className="lineage-scope-note">
            当前可见关系中 {temporalLayout.edgeStats.sourceCount.toLocaleString("zh-CN")} /{" "}
            {renderIndices.length.toLocaleString("zh-CN")} 篇文献具有出边；完整图仍只展开核心文献的一层参考文献，并非全领域完整谱系。
          </span>
        </div>
      ) : focusIndex != null ? (
        <div
          aria-label={`引用方向图例：${CITATION_FLOW_LABELS.citation}`}
          className={`citation-direction-legend ${localGraph ? "is-local" : ""}`}
          role="note"
        >
          <strong>引用方向 · {CITATION_FLOW_LABELS.citation}</strong>
          <span className="direction-legend-row">
            <span
              aria-hidden="true"
              className="direction-legend-arrow is-outgoing"
            >
              →
            </span>
            当前文献 → 参考文献（{focusRelationCounts.outgoing}）
          </span>
          <span className="direction-legend-row">
            <span
              aria-hidden="true"
              className="direction-legend-arrow is-incoming"
            >
              →
            </span>
            引用当前文献的论文 → 当前文献（{focusRelationCounts.incoming}）
          </span>
        </div>
      ) : null}

      {localGraph && isolateRootIndex != null && (
        <div className="local-graph-toolbar">
          <div>
            <strong>
              {temporalLayout ? "LOCAL DEVELOPMENT LINEAGE" : "LOCAL CITATION MAP"}
            </strong>
            <span>{data.nodes[isolateRootIndex].title}</span>
          </div>
          <div className="local-depth-switch" aria-label="局部关系深度">
            <button
              aria-pressed={isolateDepth === 1}
              className={isolateDepth === 1 ? "is-active" : ""}
              onClick={() => onIsolateDepthChange(1)}
              type="button"
            >
              1-hop
            </button>
            <button
              aria-pressed={isolateDepth === 2}
              className={isolateDepth === 2 ? "is-active" : ""}
              onClick={() => onIsolateDepthChange(2)}
              type="button"
            >
              2-hop
            </button>
          </div>
          <button
            aria-label="退出局部星图"
            className="icon-button"
            onClick={onExitIsolate}
            title="返回完整星图"
            type="button"
          >
            <X size={16} />
          </button>
        </div>
      )}

      <div className="canvas-controls" aria-label="星图视图控制">
        <button
          aria-label="放大"
          className="icon-button"
          onClick={() => updateZoom(transform.zoom * 1.45, centerAnchor)}
          title="放大"
          type="button"
        >
          <Plus size={17} />
        </button>
        <button
          aria-label="缩小"
          className="icon-button"
          onClick={() => updateZoom(transform.zoom / 1.45, centerAnchor)}
          title="缩小"
          type="button"
        >
          <Minus size={17} />
        </button>
        <button
          aria-label="回到全图"
          className="icon-button"
          onClick={resetView}
          title="回到全图"
          type="button"
        >
          <Maximize2 size={16} />
        </button>
        <button
          aria-label="聚焦选中文献"
          className="icon-button"
          disabled={selectedIndex == null}
          onClick={focusSelected}
          title="聚焦选中文献"
          type="button"
        >
          <Focus size={16} />
        </button>
      </div>

      <div className="graph-mode-switch" aria-label="星图布局模式">
        <button
          aria-pressed={layout === "constellation"}
          className={layout === "constellation" ? "is-active" : ""}
          onClick={() => onLayoutChange("constellation")}
          type="button"
        >
          <Orbit size={15} />
          领域星图
        </button>
        <button
          aria-pressed={layout === "lineage"}
          className={layout === "lineage" ? "is-active" : ""}
          onClick={() => onLayoutChange("lineage")}
          type="button"
        >
          <GitFork size={15} />
          发展脉络
        </button>
      </div>

      <div className="canvas-help">
        {temporalLayout
          ? "年份分层 · 拖拽平移 · 滚轮连续缩放 · 点击查看文献"
          : "拖拽平移 · 滚轮连续缩放 · 点击查看文献"}
      </div>
    </div>
  );
}
