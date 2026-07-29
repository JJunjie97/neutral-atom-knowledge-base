"use client";

import {
  Focus,
  Maximize2,
  Minus,
  Plus,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { nodeDegree } from "../graph-utils";
import type { GraphData } from "../types";

type Transform = {
  zoom: number;
  panX: number;
  panY: number;
};

type Point = {
  x: number;
  y: number;
};

type Props = {
  data: GraphData;
  visibleIndices: number[];
  selectedIndex: number | null;
  onSelect: (index: number | null) => void;
};

const BACKGROUND = "#09101f";
const EDGE = "rgba(128, 151, 190, 0.12)";
const EDGE_FULL = "rgba(116, 139, 178, 0.065)";
const HIGHLIGHT = "#F5D67B";

export default function GraphCanvas({
  data,
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

  const degreeLeaders = useMemo(
    () =>
      [...visibleIndices]
        .sort(
          (left, right) =>
            nodeDegree(data.nodes[right]) - nodeDegree(data.nodes[left]),
        )
        .slice(0, data.nodes.length > 1000 ? 5 : 14),
    [data.nodes, visibleIndices],
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
      const tolerance = 11 / (baseScale * transform.zoom);
      let nearest: number | null = null;
      let nearestDistance = tolerance * tolerance;

      for (const index of visibleIndices) {
        const node = data.nodes[index];
        const dx = node.x - world.x;
        const dy = node.y - world.y;
        const distance = dx * dx + dy * dy;
        if (distance < nearestDistance) {
          nearest = index;
          nearestDistance = distance;
        }
      }
      return nearest;
    },
    [baseScale, data.nodes, screenToWorld, transform.zoom, visibleIndices],
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

      context.fillStyle = "rgba(112, 142, 188, 0.16)";
      const grid = 44;
      const offsetX = ((transform.panX % grid) + grid) % grid;
      const offsetY = ((transform.panY % grid) + grid) % grid;
      for (let x = offsetX; x < size.width; x += grid) {
        for (let y = offsetY; y < size.height; y += grid) {
          context.fillRect(x, y, 1, 1);
        }
      }

      const focusIndex = selectedIndex ?? hoveredIndex;
      const focusNeighbors = new Set<number>();
      if (focusIndex != null) {
        focusNeighbors.add(focusIndex);
        for (const [source, target] of data.edges) {
          if (source === focusIndex) focusNeighbors.add(target);
          if (target === focusIndex) focusNeighbors.add(source);
        }
      }

      const drawAllEdges =
        data.nodes.length <= 1000 ||
        transform.zoom > 1.18 ||
        focusIndex != null;
      if (drawAllEdges) {
        context.beginPath();
        for (const [source, target] of data.edges) {
          if (!visibleMask[source] || !visibleMask[target]) continue;
          if (
            focusIndex != null &&
            (source === focusIndex || target === focusIndex)
          ) {
            continue;
          }
          const from = worldToScreen(data.nodes[source].x, data.nodes[source].y);
          const to = worldToScreen(data.nodes[target].x, data.nodes[target].y);
          context.moveTo(from.x, from.y);
          context.lineTo(to.x, to.y);
        }
        context.strokeStyle =
          data.nodes.length > 1000 ? EDGE_FULL : EDGE;
        context.lineWidth = 0.65;
        context.stroke();
      }

      if (focusIndex != null) {
        context.beginPath();
        for (const [source, target] of data.edges) {
          if (!visibleMask[source] || !visibleMask[target]) continue;
          if (source !== focusIndex && target !== focusIndex) continue;
          const from = worldToScreen(data.nodes[source].x, data.nodes[source].y);
          const to = worldToScreen(data.nodes[target].x, data.nodes[target].y);
          context.moveTo(from.x, from.y);
          context.lineTo(to.x, to.y);
        }
        context.strokeStyle = "rgba(245, 214, 123, 0.68)";
        context.lineWidth = 1.25;
        context.stroke();
      }

      for (const index of visibleIndices) {
        const node = data.nodes[index];
        const point = worldToScreen(node.x, node.y);
        if (
          point.x < -20 ||
          point.y < -20 ||
          point.x > size.width + 20 ||
          point.y > size.height + 20
        ) {
          continue;
        }
        const degree = nodeDegree(node);
        const isFocus = index === focusIndex;
        const isNeighbor = focusNeighbors.has(index);
        const baseRadius =
          data.nodes.length > 1000 && !node.seed
            ? 1.15
            : Math.min(8.5, 2.1 + Math.sqrt(degree + 1) * 0.34);
        const radius = isFocus ? Math.max(7, baseRadius + 2.7) : baseRadius;
        const color = colorMap.get(node.group) ?? "#7F8DA8";

        if (isFocus) {
          context.beginPath();
          context.arc(point.x, point.y, radius + 5, 0, Math.PI * 2);
          context.fillStyle = "rgba(245, 214, 123, 0.16)";
          context.fill();
        }

        context.beginPath();
        context.arc(point.x, point.y, radius, 0, Math.PI * 2);
        context.fillStyle =
          focusIndex != null && !isNeighbor ? `${color}40` : color;
        context.fill();
        if (node.seed) {
          context.strokeStyle = isFocus
            ? HIGHLIGHT
            : "rgba(255, 255, 255, 0.42)";
          context.lineWidth = isFocus ? 1.8 : 0.65;
          context.stroke();
        }
      }

      const labels = new Set<number>();
      if (transform.zoom > 1.12 && data.nodes.length <= 1000) {
        degreeLeaders.forEach((index) => labels.add(index));
      }
      if (hoveredIndex != null) labels.add(hoveredIndex);
      if (selectedIndex != null) labels.add(selectedIndex);

      context.font =
        '500 12px ui-sans-serif, "Microsoft YaHei", system-ui, sans-serif';
      context.textBaseline = "middle";
      for (const index of labels) {
        if (!visibleMask[index]) continue;
        const node = data.nodes[index];
        const point = worldToScreen(node.x, node.y);
        const title =
          node.title.length > 46 ? `${node.title.slice(0, 46)}…` : node.title;
        const width = context.measureText(title).width;
        const labelX = point.x + 11;
        const labelY = point.y;
        context.fillStyle = "rgba(5, 11, 23, 0.88)";
        context.fillRect(labelX - 5, labelY - 11, width + 10, 22);
        context.fillStyle = index === selectedIndex ? HIGHLIGHT : "#E8EDF7";
        context.fillText(title, labelX, labelY);
      }
    });

    return () => cancelAnimationFrame(frame);
  }, [
    colorMap,
    data.edges,
    data.nodes,
    degreeLeaders,
    hoveredIndex,
    selectedIndex,
    size,
    transform,
    visibleIndices,
    visibleMask,
    worldToScreen,
  ]);

  const updateZoom = useCallback(
    (nextZoom: number, anchor?: Point) => {
      const clamped = Math.max(0.35, Math.min(8, nextZoom));
      setTransform((current) => {
        if (!anchor) return { ...current, zoom: clamped };
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
    const node = data.nodes[selectedIndex];
    setTransform({
      zoom: 2.35,
      panX: -node.x * baseScale * 2.35,
      panY: -node.y * baseScale * 2.35,
    });
  }, [baseScale, data.nodes, resetView, selectedIndex]);

  return (
    <div className="graph-canvas-shell" ref={shellRef}>
      <canvas
        aria-label="可交互文献引用星图"
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
          const factor = event.deltaY > 0 ? 0.88 : 1.14;
          updateZoom(transform.zoom * factor, {
            x: event.clientX - bounds.left,
            y: event.clientY - bounds.top,
          });
        }}
        ref={canvasRef}
      />

      <div className="graph-status" aria-live="polite">
        <span className="status-dot" />
        {visibleIndices.length.toLocaleString("zh-CN")} /{" "}
        {data.nodes.length.toLocaleString("zh-CN")} 篇文献
      </div>

      <div className="canvas-controls" aria-label="星图视图控制">
        <button
          aria-label="放大"
          className="icon-button"
          onClick={() => updateZoom(transform.zoom * 1.24)}
          title="放大"
          type="button"
        >
          <Plus size={17} />
        </button>
        <button
          aria-label="缩小"
          className="icon-button"
          onClick={() => updateZoom(transform.zoom * 0.8)}
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

      <div className="canvas-help">拖拽平移 · 滚轮缩放 · 点击查看文献</div>
    </div>
  );
}
