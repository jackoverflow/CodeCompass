"use client";

import { useMemo } from "react";
import dagre from "dagre";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  type Edge,
  type Node,
  type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";

import type { Dependency } from "@/lib/api";

/** Node payload rendered by {@link FileNode}. */
type FileNodeData = {
  label: string;
  /** Lower-case extension including the dot, e.g. `.py`. */
  extension: string;
};

/** Colour scheme per language family, kept in one place for easy tuning. */
const LANGUAGE_STYLES = {
  python: {
    name: "Python",
    border: "border-blue-500 dark:border-blue-400",
    background: "bg-blue-50 dark:bg-blue-500/15",
    text: "text-blue-900 dark:text-blue-200",
    dot: "bg-blue-500",
    /** Raw hex for the MiniMap, which takes inline colours, not classes. */
    hex: "#3b82f6",
  },
  csharp: {
    name: "C#",
    border: "border-purple-500 dark:border-purple-400",
    background: "bg-purple-50 dark:bg-purple-500/15",
    text: "text-purple-900 dark:text-purple-200",
    dot: "bg-purple-500",
    hex: "#a855f7",
  },
  javascript: {
    name: "JS/TS",
    border: "border-lime-500 dark:border-lime-400",
    background: "bg-lime-50 dark:bg-lime-500/15",
    text: "text-lime-900 dark:text-lime-200",
    dot: "bg-lime-500",
    hex: "#84cc16",
  },
  other: {
    name: "Other",
    border: "border-zinc-400 dark:border-zinc-500",
    background: "bg-zinc-50 dark:bg-zinc-500/15",
    text: "text-zinc-800 dark:text-zinc-200",
    dot: "bg-zinc-400",
    hex: "#a1a1aa",
  },
} as const;

type LanguageKey = keyof typeof LANGUAGE_STYLES;

const EXTENSION_TO_LANGUAGE: Record<string, LanguageKey> = {
  ".py": "python",
  ".cs": "csharp",
  ".js": "javascript",
  ".jsx": "javascript",
  ".ts": "javascript",
  ".tsx": "javascript",
};

const NODE_WIDTH = 220;
const NODE_HEIGHT = 44;

function extensionOf(path: string): string {
  const base = path.split("/").pop() ?? path;
  const dot = base.lastIndexOf(".");
  return dot > 0 ? base.slice(dot).toLowerCase() : "";
}

function languageOf(path: string): LanguageKey {
  return EXTENSION_TO_LANGUAGE[extensionOf(path)] ?? "other";
}

function FileNode({ data }: NodeProps<FileNodeData>) {
  const style = LANGUAGE_STYLES[languageOf(data.label)];

  return (
    <div
      title={data.label}
      className={`flex h-full w-full items-center gap-2 rounded-lg border-2 px-3 shadow-sm ${style.border} ${style.background}`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-0 !bg-zinc-400 dark:!bg-zinc-500"
      />
      <span className={`h-2 w-2 shrink-0 rounded-full ${style.dot}`} />
      <span
        className={`truncate font-mono text-xs font-medium ${style.text}`}
      >
        {data.label}
      </span>
      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-0 !bg-zinc-400 dark:!bg-zinc-500"
      />
    </div>
  );
}

// Defined at module scope: React Flow warns (and re-mounts) when nodeTypes is
// a new object on every render.
const nodeTypes = { file: FileNode };

/**
 * Convert a flat dependency list into laid-out React Flow nodes and edges.
 *
 * Every distinct path (source *or* target) becomes one node; every dependency
 * becomes one edge. Duplicate edges are collapsed so a file importing the same
 * module twice does not draw two arrows.
 */
export function buildGraph(
  dependencies: Dependency[],
): { nodes: Node<FileNodeData>[]; edges: Edge[] } {
  const paths = new Set<string>();
  for (const dependency of dependencies) {
    paths.add(dependency.source_file);
    paths.add(dependency.target_file);
  }

  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: "LR", nodesep: 24, ranksep: 90, marginx: 16, marginy: 16 });

  for (const path of paths) {
    graph.setNode(path, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }

  const seen = new Set<string>();
  const edges: Edge[] = [];
  for (const dependency of dependencies) {
    const id = `${dependency.source_file}->${dependency.target_file}`;
    if (seen.has(id)) continue;
    seen.add(id);

    graph.setEdge(dependency.source_file, dependency.target_file);
    edges.push({
      id,
      source: dependency.source_file,
      target: dependency.target_file,
      type: "smoothstep",
      animated: false,
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
      style: { strokeWidth: 1.25 },
      data: { dependencyType: dependency.dependency_type },
    });
  }

  dagre.layout(graph);

  const nodes: Node<FileNodeData>[] = [...paths].map((path) => {
    const { x, y } = graph.node(path);
    return {
      id: path,
      type: "file",
      position: { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 },
      data: { label: path, extension: extensionOf(path) },
      style: { width: NODE_WIDTH, height: NODE_HEIGHT },
      draggable: true,
    };
  });

  return { nodes, edges };
}

export default function DependencyGraph({
  dependencies,
}: {
  dependencies: Dependency[];
}) {
  const { nodes, edges } = useMemo(
    () => buildGraph(dependencies),
    [dependencies],
  );

  const legend = useMemo(() => {
    const present = new Set<LanguageKey>();
    for (const dependency of dependencies) {
      present.add(languageOf(dependency.source_file));
      present.add(languageOf(dependency.target_file));
    }
    return (Object.keys(LANGUAGE_STYLES) as LanguageKey[])
      .filter((key) => present.has(key))
      .map((key) => ({ key, ...LANGUAGE_STYLES[key] }));
  }, [dependencies]);

  if (dependencies.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-300 bg-white px-6 py-10 text-center text-sm text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400">
        No dependencies found — nothing to map yet.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {nodes.length} files · {edges.length} edges
        </p>
        <ul className="flex flex-wrap items-center gap-4">
          {legend.map((entry) => (
            <li
              key={entry.key}
              className="flex items-center gap-1.5 text-xs text-zinc-600 dark:text-zinc-300"
            >
              <span className={`h-2.5 w-2.5 rounded-sm ${entry.dot}`} />
              {entry.name}
            </li>
          ))}
        </ul>
      </div>

      <div className="h-[520px] w-full bg-zinc-50 dark:bg-zinc-950">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.1}
          maxZoom={2}
          nodesConnectable={false}
          proOptions={{ hideAttribution: false }}
          className="[&_.react-flow__edge-path]:stroke-zinc-400 dark:[&_.react-flow__edge-path]:stroke-zinc-600 [&_.react-flow__arrowhead]:fill-zinc-400"
        >
          <Background gap={16} size={1} />
          <Controls showInteractive={false} />
          <MiniMap
            pannable
            zoomable
            nodeColor={(node) => LANGUAGE_STYLES[languageOf(node.data.label)].hex}
          />
        </ReactFlow>
      </div>
    </div>
  );
}
