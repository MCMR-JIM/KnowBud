import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import * as d3 from 'd3';
import type { SimulationLinkDatum, SimulationNodeDatum, ZoomTransform } from 'd3';
import * as echarts from 'echarts/core';
import { BarChart, LineChart, RadarChart } from 'echarts/charts';
import { GridComponent, LegendComponent, RadarComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { AlertCircle, BookOpen, CheckCircle2, Clock, FileText, Loader2, Maximize2, Minimize2, Network, Pencil, Plus, Trash2, UploadCloud, Video, X } from 'lucide-react';
import { API_BASE } from '../api/config';
import { KnowledgeAPI, ResourceAPI } from '../api/client';
import { useAppDialog } from '../components/AppDialog';
import SettingsPanel from '../components/SettingsPanel';
import LanguageSwitcher from '../i18n/LanguageSwitcher';
import i18n from '../i18n';

const LLM_NOT_CONFIGURED_MESSAGE = '尚未配置模型，请前往设置页面配置远程 API 或本地模型';

function getErrorMessage(error: unknown): string {
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object') {
    const maybeError = error as {
      message?: string;
      response?: { data?: { detail?: string; error?: string } };
    };
    return maybeError.response?.data?.detail || maybeError.response?.data?.error || maybeError.message || '';
  }
  return '';
}

function isLlmNotConfiguredError(error: unknown): boolean {
  return getErrorMessage(error).includes('LLM not configured');
}

echarts.use([BarChart, LineChart, RadarChart, GridComponent, LegendComponent, RadarComponent, TooltipComponent, CanvasRenderer]);

type GraphTopic = {
  topic_id: string;
  title: string;
  difficulty?: number;
  parent_ids?: string[];
  prerequisite_ids?: string[];
  tags?: string[];
  resources?: unknown[];
};

type TopicResource = {
  resource_id: string;
  resource_name: string;
  media_type: string;
  original_filename: string;
  size_bytes: number;
  topic_id?: string;
  ingestion_status: string;
  ingestion_stage?: string;
  ingestion_error?: string;
  extracted_node_count?: number;
  pipeline_stage?: string;
  candidate_node_count?: number;
};

type SubjectModalMode = 'create' | 'edit';

type LearningDashboardData = {
  todayStar: number;
  todayStarIncrease: number;
  focusTime: number;
  questionActiveness: string;
  progressData: { day: string; score: number }[];
  radarData: {
    questionActiveness: number;
    focus: number;
    thinking: number;
    logic: number;
    knowledge: number;
  };
};

type GraphCanvasNode = SimulationNodeDatum & {
  id: string;
  title: string;
  edgeCount: number;
  radius: number;
  collisionRadius: number;
  topic: GraphTopic;
  isRoot: boolean;
  isMistake: boolean;
  subject: string;
  targetX?: number;
  targetY?: number;
  layoutDepth?: number;
  layoutOrder?: number;
};

type GraphCanvasLink = SimulationLinkDatum<GraphCanvasNode> & {
  source: string | GraphCanvasNode;
  target: string | GraphCanvasNode;
  type: 'parent' | 'prereq' | 'both';
};

type GraphCanvasSelectionMeta = {
  resourceCount: number;
  mistakeCount: number;
  lastReview?: string | null;
};

const getNodeEdgeCount = (topic: GraphTopic, allTopics: GraphTopic[]) => {
  const parentCount = topic.parent_ids?.length || 0;
  const prerequisiteCount = topic.prerequisite_ids?.length || 0;
  const childCount = allTopics.filter((candidate) => (candidate.parent_ids || []).includes(topic.topic_id)).length;
  const successorCount = allTopics.filter((candidate) => (candidate.prerequisite_ids || []).includes(topic.topic_id)).length;
  return parentCount + prerequisiteCount + childCount + successorCount;
};

const getSubjectTag = (tags: string[] = []) => {
  const tag = tags.find((item) => item.startsWith('subject:'));
  return tag ? tag.slice('subject:'.length) : '';
};

const getSubjectLanguageId = (tags: string[] = []) => {
  const tag = tags.find((item) => item.startsWith('language:'));
  return tag ? tag.slice('language:'.length) : null;
};

const stripFileExtension = (filename: string) => filename.replace(/\.[^.]+$/, '') || filename;

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const linkKeyOf = (sourceId: string, targetId: string) => `${sourceId}->${targetId}`;

const mean = (values: number[]) => {
  if (values.length === 0) return Number.NaN;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
};

const reorderLayer = (
  layer: string[],
  anchorPositions: Map<string, number>,
  neighborIdsByNode: Map<string, string[]>,
) => {
  const previousOrder = new Map(layer.map((id, index) => [id, index]));
  return layer.slice().sort((leftId, rightId) => {
    const leftNeighbors = (neighborIdsByNode.get(leftId) || [])
      .map((id) => anchorPositions.get(id))
      .filter((value): value is number => value !== undefined);
    const rightNeighbors = (neighborIdsByNode.get(rightId) || [])
      .map((id) => anchorPositions.get(id))
      .filter((value): value is number => value !== undefined);
    const leftScore = mean(leftNeighbors);
    const rightScore = mean(rightNeighbors);
    const normalizedLeft = Number.isNaN(leftScore) ? previousOrder.get(leftId) || 0 : leftScore;
    const normalizedRight = Number.isNaN(rightScore) ? previousOrder.get(rightId) || 0 : rightScore;
    if (normalizedLeft !== normalizedRight) return normalizedLeft - normalizedRight;
    return (previousOrder.get(leftId) || 0) - (previousOrder.get(rightId) || 0);
  });
};

const buildShortestParentPath = (
  selectedId: string,
  parentIncoming: Map<string, string[]>,
  nodeById: Map<string, GraphCanvasNode>,
) => {
  const queue = [selectedId];
  const childByParent = new Map<string, string>();
  const visited = new Set(queue);
  let reachedRootId: string | null = null;

  while (queue.length > 0) {
    const currentId = queue.shift() || '';
    const node = nodeById.get(currentId);
    const parentIds = parentIncoming.get(currentId) || [];
    if ((node?.isRoot || parentIds.length === 0) && currentId !== selectedId) {
      reachedRootId = currentId;
      break;
    }
    for (const parentId of parentIds) {
      if (visited.has(parentId)) continue;
      visited.add(parentId);
      childByParent.set(parentId, currentId);
      queue.push(parentId);
    }
  }

  const pathEdgeKeys = new Set<string>();
  const pathNodeIds = new Set<string>([selectedId]);
  if (!reachedRootId) return { pathEdgeKeys, pathNodeIds };

  let currentId = reachedRootId;
  pathNodeIds.add(currentId);
  while (childByParent.has(currentId)) {
    const childId = childByParent.get(currentId) || '';
    pathNodeIds.add(childId);
    pathEdgeKeys.add(linkKeyOf(currentId, childId));
    currentId = childId;
  }

  return { pathEdgeKeys, pathNodeIds };
};

function KnowledgeGraphCanvas({
  topics,
  selectedTopicId,
  mistakeTopicIds,
  nodeMetaByTopicId,
  onSelectNode,
}: {
  topics: GraphTopic[];
  selectedTopicId?: string;
  mistakeTopicIds: string[];
  nodeMetaByTopicId: ReadonlyMap<string, GraphCanvasSelectionMeta>;
  onSelectNode: (topic: GraphTopic | null) => void;
}) {
  const t = i18n.getFixedT(i18n.language);
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const onSelectNodeRef = useRef(onSelectNode);
  const selectedTopicIdRef = useRef<string | undefined>(selectedTopicId);
  const nodeMetaByTopicIdRef = useRef(nodeMetaByTopicId);
  const redrawRef = useRef<(() => void) | null>(null);
  const transformRef = useRef<ZoomTransform>(d3.zoomIdentity);
  const positionCacheRef = useRef<Map<string, { x: number; y: number }>>(new Map());
  const topologySignatureRef = useRef('');
  const mistakeKey = mistakeTopicIds.join('|');

  useEffect(() => {
    onSelectNodeRef.current = onSelectNode;
  }, [onSelectNode]);

  useEffect(() => {
    selectedTopicIdRef.current = selectedTopicId;
    redrawRef.current?.();
  }, [selectedTopicId]);

  useEffect(() => {
    nodeMetaByTopicIdRef.current = nodeMetaByTopicId;
    redrawRef.current?.();
  }, [nodeMetaByTopicId]);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas || topics.length === 0) return;

    let stopRender = () => {};

    const render = () => {
      stopRender();
      const rect = container.getBoundingClientRect();
      const width = Math.max(420, Math.floor(rect.width));
      const height = Math.max(360, Math.floor(rect.height));
      const pixelRatio = window.devicePixelRatio || 1;
      canvas.width = width * pixelRatio;
      canvas.height = height * pixelRatio;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const mistakeSet = new Set(mistakeTopicIds);
      const validIds = new Set(topics.map((topic) => topic.topic_id));
      const topologySignature = topics
        .map((topic) => `${topic.topic_id}|${(topic.parent_ids || []).slice().sort().join(',')}|${(topic.prerequisite_ids || []).slice().sort().join(',')}`)
        .sort()
        .join(';');
      const isSameTopology = topologySignatureRef.current === topologySignature;
      const cachedPositions = positionCacheRef.current;
      const nodes: GraphCanvasNode[] = topics.map((topic) => {
        const isRoot = (topic.tags || []).includes('facet:root');
        const edgeWeight = getNodeEdgeCount(topic, topics);
        const labelWidth = Math.min(172, Math.max(64, topic.title.length * 11 + 22));
        const nodeRadius = isRoot ? 20 : clamp(9 + edgeWeight * 1.55, 9, 18);
        return {
          id: topic.topic_id,
          title: topic.title,
          edgeCount: edgeWeight,
          topic,
          isRoot,
          isMistake: mistakeSet.has(topic.topic_id),
          subject: getSubjectTag(topic.tags || []) || 'general',
          radius: nodeRadius,
          collisionRadius: Math.max(nodeRadius + 14, labelWidth / 2 + 8),
          x: cachedPositions.get(topic.topic_id)?.x ?? width / 2,
          y: cachedPositions.get(topic.topic_id)?.y ?? height / 2,
        };
      });
      const nodeById = new Map(nodes.map((node) => [node.id, node]));
      const linkByPair = new Map<string, GraphCanvasLink>();
      const upsertLink = (source: string, target: string, type: 'parent' | 'prereq') => {
        const key = linkKeyOf(source, target);
        const existing = linkByPair.get(key);
        if (!existing) {
          linkByPair.set(key, { source, target, type });
          return;
        }
        if (existing.type !== type) existing.type = 'both';
      };

      for (const topic of topics) {
        for (const parentId of topic.parent_ids || []) {
          if (validIds.has(parentId)) upsertLink(parentId, topic.topic_id, 'parent');
        }
        for (const parentId of topic.prerequisite_ids || []) {
          if (validIds.has(parentId)) upsertLink(parentId, topic.topic_id, 'prereq');
        }
      }
      const links = Array.from(linkByPair.values());

      const allOutgoing = new Map<string, string[]>();
      const allIncoming = new Map<string, string[]>();
      const parentOutgoing = new Map<string, string[]>();
      const parentIncoming = new Map<string, string[]>();
      const incidentLinkKeysByNode = new Map<string, string[]>();
      const incomingCount = new Map(nodes.map((node) => [node.id, 0]));
      for (const link of links) {
        const sourceId = String(link.source);
        const targetId = String(link.target);
        allOutgoing.set(sourceId, [...(allOutgoing.get(sourceId) || []), targetId]);
        allIncoming.set(targetId, [...(allIncoming.get(targetId) || []), sourceId]);
        incidentLinkKeysByNode.set(sourceId, [...(incidentLinkKeysByNode.get(sourceId) || []), linkKeyOf(sourceId, targetId)]);
        incidentLinkKeysByNode.set(targetId, [...(incidentLinkKeysByNode.get(targetId) || []), linkKeyOf(sourceId, targetId)]);
        if (link.type === 'parent' || link.type === 'both') {
          parentOutgoing.set(sourceId, [...(parentOutgoing.get(sourceId) || []), targetId]);
          parentIncoming.set(targetId, [...(parentIncoming.get(targetId) || []), sourceId]);
        }
        incomingCount.set(targetId, (incomingCount.get(targetId) || 0) + 1);
      }

      const rootNodes = nodes.filter((node) => node.isRoot);
      const layoutRoots = (rootNodes.length ? rootNodes : nodes.filter((node) => (incomingCount.get(node.id) || 0) === 0)).slice();
      if (layoutRoots.length === 0 && nodes[0]) layoutRoots.push(nodes[0]);

      const indegree = new Map(nodes.map((node) => [node.id, allIncoming.get(node.id)?.length || 0]));
      const topoQueue = layoutRoots.map((node) => node.id);
      const queued = new Set(topoQueue);
      for (const node of nodes) {
        if ((indegree.get(node.id) || 0) === 0 && !queued.has(node.id)) {
          topoQueue.push(node.id);
          queued.add(node.id);
        }
      }

      const topoOrder: string[] = [];
      while (topoQueue.length > 0) {
        const currentId = topoQueue.shift() || '';
        topoOrder.push(currentId);
        for (const nextId of allOutgoing.get(currentId) || []) {
          const nextIn = (indegree.get(nextId) || 0) - 1;
          indegree.set(nextId, nextIn);
          if (nextIn === 0) topoQueue.push(nextId);
        }
      }

      for (const node of nodes) {
        if (!topoOrder.includes(node.id)) topoOrder.push(node.id);
      }

      const rootById = new Map<string, string>();
      const componentQueue = layoutRoots.map((node) => node.id);
      for (const rootId of componentQueue) rootById.set(rootId, rootId);
      while (componentQueue.length > 0) {
        const currentId = componentQueue.shift() || '';
        const rootId = rootById.get(currentId) || currentId;
        for (const targetId of allOutgoing.get(currentId) || []) {
          if (rootById.has(targetId)) continue;
          rootById.set(targetId, rootId);
          componentQueue.push(targetId);
        }
      }
      for (const node of nodes) {
        if (!rootById.has(node.id)) rootById.set(node.id, node.id);
      }

      const depthById = new Map<string, number>(nodes.map((node) => [node.id, 0]));
      for (const nodeId of topoOrder) {
        const baseDepth = depthById.get(nodeId) || 0;
        for (const targetId of allOutgoing.get(nodeId) || []) {
          depthById.set(targetId, Math.max(depthById.get(targetId) || 0, baseDepth + 1));
        }
      }

      const componentIds = Array.from(new Set(nodes.map((node) => rootById.get(node.id) || node.id))).sort((leftId, rightId) => {
        const leftNode = nodeById.get(leftId);
        const rightNode = nodeById.get(rightId);
        return (leftNode?.title || leftId).localeCompare(rightNode?.title || rightId, 'zh-CN');
      });
      const componentLayouts = componentIds.map((componentId) => {
        const componentNodes = nodes
          .filter((node) => (rootById.get(node.id) || node.id) === componentId)
          .sort((left, right) => {
            const leftIn = allIncoming.get(left.id)?.length || 0;
            const rightIn = allIncoming.get(right.id)?.length || 0;
            if (leftIn !== rightIn) return leftIn - rightIn;
            return left.title.localeCompare(right.title, 'zh-CN');
          });
        const componentMaxDepth = Math.max(0, ...componentNodes.map((node) => depthById.get(node.id) || 0));
        const layers = Array.from({ length: componentMaxDepth + 1 }, () => [] as string[]);
        componentNodes.forEach((node) => {
          const depth = depthById.get(node.id) || 0;
          node.layoutDepth = depth;
          layers[depth].push(node.id);
        });

        for (let iteration = 0; iteration < 8; iteration += 1) {
          let anchorPositions = new Map(layers[0].map((id, index) => [id, index]));
          for (let depth = 1; depth < layers.length; depth += 1) {
            layers[depth] = reorderLayer(layers[depth], anchorPositions, allIncoming);
            anchorPositions = new Map(layers[depth].map((id, index) => [id, index]));
          }

          anchorPositions = new Map(layers[layers.length - 1].map((id, index) => [id, index]));
          for (let depth = layers.length - 2; depth >= 0; depth -= 1) {
            layers[depth] = reorderLayer(layers[depth], anchorPositions, allOutgoing);
            anchorPositions = new Map(layers[depth].map((id, index) => [id, index]));
          }
        }

        return {
          componentId,
          layers,
          maxDepth: componentMaxDepth,
          maxLayerSize: Math.max(1, ...layers.map((layer) => layer.length)),
        };
      });

      const graphPadding = { top: 56, right: 72, bottom: 56, left: 48 };
      const usableWidth = Math.max(320, width - graphPadding.left - graphPadding.right);
      const usableHeight = Math.max(260, height - graphPadding.top - graphPadding.bottom);
      const totalWeight = componentLayouts.reduce((sum, layout) => sum + Math.max(3, layout.maxLayerSize + layout.maxDepth * 0.35), 0);
      const componentGap = clamp(usableHeight * 0.035, 18, 34);
      const availableHeight = usableHeight - componentGap * Math.max(0, componentLayouts.length - 1);
      let bandTop = graphPadding.top;

      componentLayouts.forEach((layout, componentIndex) => {
        const weight = Math.max(3, layout.maxLayerSize + layout.maxDepth * 0.35);
        const bandHeight = componentLayouts.length === 1
          ? availableHeight
          : Math.max(140, availableHeight * (weight / Math.max(1, totalWeight)));
        const centerY = bandTop + bandHeight / 2;
        const boxWidth = usableWidth;
        const rootInset = componentLayouts.length === 1 ? boxWidth * 0.14 : boxWidth * 0.12;
        const rootX = graphPadding.left + rootInset;
        const radiusStep = (boxWidth - rootInset - 48) / Math.max(1, layout.maxDepth + 0.65);
        const verticalRadiusScale = clamp(bandHeight / Math.max(220, boxWidth * 0.78), 0.5, 1.15);

        layout.layers.forEach((layer, depth) => {
          const spreadBase = layout.layers.length === 1 ? Math.PI * 1.15 : Math.PI * clamp(0.36 + layer.length * 0.045, 0.5, 0.96);
          const radius = depth === 0 ? 0 : 24 + depth * radiusStep;
          layer.forEach((nodeId, index) => {
            const node = nodeById.get(nodeId);
            if (!node) return;
            node.layoutOrder = index;
            if (depth === 0) {
              node.targetX = rootX;
              node.targetY = centerY;
            } else {
              const angle = layer.length === 1
                ? 0
                : -spreadBase / 2 + (spreadBase * (index + 0.5)) / layer.length;
              node.targetX = rootX + Math.cos(angle) * radius;
              node.targetY = centerY + Math.sin(angle) * radius * verticalRadiusScale;
            }
            if (!isSameTopology || !cachedPositions.has(node.id)) {
              node.x = node.targetX + (Math.random() - 0.5) * 22;
              node.y = node.targetY + (Math.random() - 0.5) * 22;
            }
          });
        });

        bandTop += bandHeight + (componentIndex < componentLayouts.length - 1 ? componentGap : 0);
      });

      let transform: ZoomTransform = transformRef.current;
      const simulation = d3.forceSimulation<GraphCanvasNode>(nodes)
        .force('link', d3.forceLink<GraphCanvasNode, GraphCanvasLink>(links)
          .id((node) => node.id)
          .distance((link) => {
            const sourceNode = typeof link.source === 'string' ? nodeById.get(link.source) : link.source;
            const targetNode = typeof link.target === 'string' ? nodeById.get(link.target) : link.target;
            const depthGap = Math.abs((targetNode?.layoutDepth || 0) - (sourceNode?.layoutDepth || 0));
            return 48 + depthGap * 34 + (link.type === 'prereq' ? 10 : 0);
          })
          .strength((link) => link.type === 'both' ? 0.22 : link.type === 'prereq' ? 0.18 : 0.16)
          .iterations(4))
        .force('charge', d3.forceManyBody<GraphCanvasNode>()
          .strength((node) => node.isRoot ? -140 : -(42 + node.edgeCount * 7))
          .distanceMin(24)
          .distanceMax(220))
        .force('x', d3.forceX<GraphCanvasNode>((node) => node.targetX ?? width / 2).strength(0.62))
        .force('y', d3.forceY<GraphCanvasNode>((node) => node.targetY ?? height / 2).strength(0.34))
        .force('collide', d3.forceCollide<GraphCanvasNode>((node) => node.collisionRadius).strength(0.9).iterations(2))
        .velocityDecay(0.22)
        .alpha(isSameTopology ? 0.42 : 1)
        .alphaDecay(isSameTopology ? 0.009 : 0.006)
        .alphaMin(0.0012);

      const drawPill = (x: number, y: number, pillWidth: number, pillHeight: number, radius: number) => {
        ctx.beginPath();
        ctx.moveTo(x + radius, y);
        ctx.lineTo(x + pillWidth - radius, y);
        ctx.quadraticCurveTo(x + pillWidth, y, x + pillWidth, y + radius);
        ctx.lineTo(x + pillWidth, y + pillHeight - radius);
        ctx.quadraticCurveTo(x + pillWidth, y + pillHeight, x + pillWidth - radius, y + pillHeight);
        ctx.lineTo(x + radius, y + pillHeight);
        ctx.quadraticCurveTo(x, y + pillHeight, x, y + pillHeight - radius);
        ctx.lineTo(x, y + radius);
        ctx.quadraticCurveTo(x, y, x + radius, y);
        ctx.closePath();
      };

      const drawArrowHead = (x: number, y: number, angle: number, color: string, size: number) => {
        ctx.save();
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x - size * Math.cos(angle - Math.PI / 6), y - size * Math.sin(angle - Math.PI / 6));
        ctx.lineTo(x - size * Math.cos(angle + Math.PI / 6), y - size * Math.sin(angle + Math.PI / 6));
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      };

      const drawBubble = (node: GraphCanvasNode) => {
        const meta = nodeMetaByTopicIdRef.current.get(node.id);
        const nodeX = node.x || 0;
        const nodeY = node.y || 0;
        const screenX = transform.applyX(nodeX);
        const screenY = transform.applyY(nodeY);
        const anchorOffset = Math.max(24, node.radius * transform.k + 18);
        const bubbleWidth = 246;
        const bubbleHeight = 132;
        let bubbleX = screenX + anchorOffset;
        if (bubbleX + bubbleWidth > width - 18) {
          bubbleX = screenX - bubbleWidth - anchorOffset;
        }
        const bubbleY = clamp(screenY - bubbleHeight / 2, 18, height - bubbleHeight - 18);
        const pointerOnRight = bubbleX > screenX;
        const pointerY = clamp(screenY, bubbleY + 18, bubbleY + bubbleHeight - 18);

        ctx.save();
        ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
        ctx.shadowColor = 'rgba(2, 6, 23, 0.38)';
        ctx.shadowBlur = 26;
        ctx.shadowOffsetY = 12;
        ctx.fillStyle = 'rgba(15, 23, 42, 0.96)';
        drawPill(bubbleX, bubbleY, bubbleWidth, bubbleHeight, 18);
        ctx.fill();
        ctx.shadowColor = 'transparent';

        ctx.beginPath();
        if (pointerOnRight) {
          ctx.moveTo(bubbleX, pointerY - 11);
          ctx.lineTo(bubbleX - 14, screenY);
          ctx.lineTo(bubbleX, pointerY + 11);
        } else {
          ctx.moveTo(bubbleX + bubbleWidth, pointerY - 11);
          ctx.lineTo(bubbleX + bubbleWidth + 14, screenY);
          ctx.lineTo(bubbleX + bubbleWidth, pointerY + 11);
        }
        ctx.closePath();
        ctx.fill();

        ctx.strokeStyle = 'rgba(251, 191, 36, 0.6)';
        ctx.lineWidth = 1.5;
        drawPill(bubbleX, bubbleY, bubbleWidth, bubbleHeight, 18);
        ctx.stroke();

        ctx.fillStyle = '#f8fafc';
        ctx.font = '800 15px Nunito, Segoe UI, sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(node.title, bubbleX + 16, bubbleY + 14);

        ctx.fillStyle = 'rgba(224, 231, 255, 0.82)';
        ctx.font = '700 11px Nunito, Segoe UI, sans-serif';
        ctx.fillText(t('admin.graph.nodeInfo'), bubbleX + 16, bubbleY + 38);

        const metrics = [
          `${t('admin.graph.boundResources')} ${meta?.resourceCount ?? 0}`,
          `${t('admin.graph.mistakeHits')} ${meta?.mistakeCount ?? (node.isMistake ? 1 : 0)}`,
          meta?.lastReview ? `${meta.lastReview}` : t('admin.graph.stable'),
        ];

        ctx.font = '700 12px Nunito, Segoe UI, sans-serif';
        metrics.forEach((line, index) => {
          ctx.fillStyle = index < 2 ? '#fde68a' : 'rgba(226, 232, 240, 0.92)';
          ctx.fillText(line, bubbleX + 16, bubbleY + 60 + index * 22);
        });
        ctx.restore();
      };

      const findHitNode = (x: number, y: number) => {
        for (let index = nodes.length - 1; index >= 0; index -= 1) {
          const node = nodes[index];
          const dx = x - (node.x || 0);
          const dy = y - (node.y || 0);
          if (Math.hypot(dx, dy) <= node.radius + 10) return node;
        }
        return undefined;
      };

      const draw = () => {
        const selectedId = selectedTopicIdRef.current;
        const selectedNode = selectedId ? nodeById.get(selectedId) : undefined;
        const { pathEdgeKeys, pathNodeIds } = selectedNode
          ? buildShortestParentPath(selectedNode.id, parentIncoming, nodeById)
          : { pathEdgeKeys: new Set<string>(), pathNodeIds: new Set<string>() };
        const selectedIncidentEdgeKeys = new Set(selectedId ? incidentLinkKeysByNode.get(selectedId) || [] : []);

        ctx.save();
        ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
        ctx.clearRect(0, 0, width, height);
        ctx.translate(transform.x, transform.y);
        ctx.scale(transform.k, transform.k);

        for (const link of links) {
          if (typeof link.source === 'string' || typeof link.target === 'string') continue;
          const sx = link.source.x || 0;
          const sy = link.source.y || 0;
          const tx = link.target.x || 0;
          const ty = link.target.y || 0;
          const dx = tx - sx;
          const dy = ty - sy;
          const length = Math.hypot(dx, dy);
          if (length <= 1) continue;
          const ux = dx / length;
          const uy = dy / length;
          const startX = sx + ux * (link.source.radius + 3);
          const startY = sy + uy * (link.source.radius + 3);
          const endX = tx - ux * (link.target.radius + 6);
          const endY = ty - uy * (link.target.radius + 6);
          const sourceId = typeof link.source === 'string' ? link.source : link.source.id;
          const targetId = typeof link.target === 'string' ? link.target : link.target.id;
          const currentLinkKey = linkKeyOf(sourceId, targetId);
          const isPathLink = pathEdgeKeys.has(currentLinkKey);
          const isIncidentLink = selectedIncidentEdgeKeys.has(currentLinkKey);
          const linkColor = isPathLink
            ? 'rgba(250, 204, 21, 0.96)'
            : isIncidentLink
              ? 'rgba(255, 255, 255, 0.88)'
              : link.type === 'parent'
                ? 'rgba(244, 114, 182, 0.42)'
                : link.type === 'both'
                  ? 'rgba(251, 191, 36, 0.54)'
                  : 'rgba(125, 211, 252, 0.42)';
          const controlOffset = clamp(Math.abs(dx) * 0.35, 26, 112);
          const curveSign = dy >= 0 ? 1 : -1;
          const curveOffset = link.type === 'prereq'
            ? clamp(Math.abs(dy) * 0.18 + 16, 18, 52) * curveSign
            : 0;
          const endControlX = endX - controlOffset;
          const endControlY = endY + curveOffset;

          ctx.beginPath();
          ctx.moveTo(startX, startY);
          ctx.bezierCurveTo(
            startX + controlOffset,
            startY - curveOffset,
            endControlX,
            endControlY,
            endX,
            endY,
          );
          ctx.strokeStyle = linkColor;
          ctx.lineWidth = isPathLink ? 3.5 : isIncidentLink ? 2.4 : link.type === 'both' ? 1.6 : 1.35;
          if (isPathLink) {
            ctx.setLineDash([]);
          } else if (link.type === 'parent') {
            ctx.setLineDash([6, 7]);
          } else if (link.type === 'both') {
            ctx.setLineDash([9, 5, 2, 5]);
          } else {
            ctx.setLineDash([]);
          }
          ctx.stroke();
          ctx.setLineDash([]);
          drawArrowHead(endX, endY, Math.atan2(endY - endControlY, endX - endControlX), linkColor, isPathLink ? 10 : link.type === 'both' ? 8 : 7);
        }
        ctx.setLineDash([]);

        for (const node of nodes) {
          const x = node.x || 0;
          const y = node.y || 0;
          const isSelected = node.id === selectedId;
          const isOnPath = pathNodeIds.has(node.id);
          const haloRadius = node.radius + (node.isMistake ? 9 : 6);

          const halo = ctx.createRadialGradient(x, y, node.radius * 0.4, x, y, haloRadius);
          halo.addColorStop(0, isSelected ? 'rgba(250, 204, 21, 0.36)' : node.isMistake ? 'rgba(244, 63, 94, 0.26)' : 'rgba(129, 140, 248, 0.2)');
          halo.addColorStop(1, 'rgba(15, 23, 42, 0)');
          ctx.fillStyle = halo;
          ctx.beginPath();
          ctx.arc(x, y, haloRadius, 0, Math.PI * 2);
          ctx.fill();

          ctx.beginPath();
          ctx.arc(x, y, node.radius, 0, Math.PI * 2);
          ctx.fillStyle = node.isRoot ? '#fce7f3' : node.isMistake ? '#ffe4e6' : '#eef2ff';
          ctx.fill();
          ctx.strokeStyle = isSelected ? '#facc15' : isOnPath ? '#fbbf24' : node.isMistake ? '#fb7185' : node.isRoot ? '#f472b6' : '#93c5fd';
          ctx.lineWidth = isSelected ? 3.2 : isOnPath ? 2.4 : 1.6;
          ctx.stroke();

          ctx.fillStyle = node.isRoot ? '#be185d' : node.isMistake ? '#be123c' : '#1e3a8a';
          ctx.font = `800 ${node.isRoot ? 11 : 10}px Nunito, Segoe UI, sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(node.isRoot ? 'ROOT' : String(node.edgeCount), x, y);

          const label = node.title.length > 16 ? `${node.title.slice(0, 16)}...` : node.title;
          ctx.font = '700 11px Nunito, Segoe UI, sans-serif';
          const labelWidth = Math.min(156, ctx.measureText(label).width + 18);
          const labelX = x - labelWidth / 2;
          const labelY = y + node.radius + 7;
          ctx.fillStyle = isSelected ? 'rgba(250, 204, 21, 0.92)' : isOnPath ? 'rgba(245, 158, 11, 0.88)' : 'rgba(15, 23, 42, 0.74)';
          drawPill(labelX, labelY, labelWidth, 20, 10);
          ctx.fill();
          ctx.fillStyle = isSelected ? '#111827' : '#f8fafc';
          ctx.fillText(label, x, labelY + 10);
        }

        ctx.restore();

        if (selectedNode) {
          drawBubble(selectedNode);
        }
      };

      simulation.on('tick', () => {
        positionCacheRef.current = new Map(nodes.map((node) => [node.id, { x: node.x || 0, y: node.y || 0 }]));
        draw();
      });
      simulation.on('end', () => {
        positionCacheRef.current = new Map(nodes.map((node) => [node.id, { x: node.x || 0, y: node.y || 0 }]));
        draw();
      });
      topologySignatureRef.current = topologySignature;
      redrawRef.current = draw;

      const selection = d3.select<HTMLCanvasElement, unknown>(canvas);
      selection.on('.zoom', null).on('.drag', null).on('click', null);

      const zoom = d3.zoom<HTMLCanvasElement, unknown>()
        .scaleExtent([0.45, 4.5])
        .on('zoom', (event) => {
          transform = event.transform;
          transformRef.current = transform;
          draw();
        });

      const pointerInGraph = (event: MouseEvent | TouchEvent) => transform.invert(d3.pointer(event, canvas));

      const drag = d3.drag<HTMLCanvasElement, unknown>()
        .container(canvas)
        .subject((event) => {
          const [x, y] = pointerInGraph(event.sourceEvent);
          return simulation.find(x, y, 28 / Math.max(0.85, transform.k)) || findHitNode(x, y) || undefined;
        })
        .on('start', (event) => {
          const subject = event.subject as GraphCanvasNode | undefined;
          if (!subject) return;
          subject.fx = subject.x;
          subject.fy = subject.y;
          simulation.alphaTarget(0.03).restart();
        })
        .on('drag', (event) => {
          const subject = event.subject as GraphCanvasNode | undefined;
          if (!subject) return;
          const [x, y] = pointerInGraph(event.sourceEvent);
          subject.fx = x;
          subject.fy = y;
          positionCacheRef.current.set(subject.id, { x, y });
        })
        .on('end', (event) => {
          const subject = event.subject as GraphCanvasNode | undefined;
          if (!subject) return;
          simulation.alphaTarget(0);
          subject.fx = null;
          subject.fy = null;
          simulation.restart();
        });

      selection.call(zoom).call(drag);
      selection.on('click', (event) => {
        const [x, y] = pointerInGraph(event);
        const hit = simulation.find(x, y, 24 / Math.max(0.85, transform.k)) || findHitNode(x, y);
        selectedTopicIdRef.current = hit?.id;
        onSelectNodeRef.current(hit ? hit.topic : null);
        draw();
      });
      draw();
      simulation.restart();

      stopRender = () => {
        simulation.stop();
        positionCacheRef.current = new Map(nodes.map((node) => [node.id, { x: node.x || 0, y: node.y || 0 }]));
        if (redrawRef.current === draw) redrawRef.current = null;
        selection.on('.zoom', null).on('.drag', null).on('click', null);
      };
    };

    render();
    const observer = new ResizeObserver(render);
    observer.observe(container);

    return () => {
      observer.disconnect();
      stopRender();
    };
  }, [topics, mistakeKey]);

  return (
    <div ref={containerRef} className="relative h-full w-full">
      <canvas ref={canvasRef} className="h-full w-full cursor-grab active:cursor-grabbing" />
    </div>
  );
}

function LearningReportCharts({ data }: { data: LearningDashboardData }) {
  const { t } = useTranslation();
  const trendRef = useRef<HTMLDivElement>(null);
  const radarRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const trendEl = trendRef.current;
    if (!trendEl) return;

    const chart = echarts.init(trendEl, undefined, { renderer: 'canvas' });
    const days = data.progressData.map((item) => item.day);
    const scores = data.progressData.map((item) => item.score);
    chart.setOption({
      color: ['#f472b6', '#38bdf8'],
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(15,23,42,0.92)',
        borderWidth: 0,
        textStyle: { color: '#fff', fontWeight: 700 },
        axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(244,114,182,0.08)' } },
      },
      legend: {
        top: 8,
        right: 10,
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { color: '#64748b', fontWeight: 700 },
      },
      grid: { left: 18, right: 18, top: 48, bottom: 22, containLabel: true },
      xAxis: {
        type: 'category',
        data: days,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: '#fbcfe8' } },
        axisLabel: { color: '#64748b', fontWeight: 800 },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        splitLine: { lineStyle: { color: 'rgba(244,114,182,0.14)', type: 'dashed' } },
        axisLabel: { color: '#94a3b8', fontWeight: 700 },
      },
      series: [
        {
          name: t('admin.report.dailyEnergy'),
          type: 'bar',
          data: scores,
          barWidth: 18,
          itemStyle: {
            borderRadius: [10, 10, 4, 4],
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#fb7185' },
              { offset: 0.55, color: '#f9a8d4' },
              { offset: 1, color: '#fdf2f8' },
            ]),
          },
        },
        {
          name: t('admin.report.trendCurve'),
          type: 'line',
          data: scores,
          smooth: true,
          symbol: 'circle',
          symbolSize: 8,
          lineStyle: { width: 4, color: '#0ea5e9' },
          itemStyle: { color: '#0ea5e9', borderColor: '#fff', borderWidth: 3 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(14,165,233,0.22)' },
              { offset: 1, color: 'rgba(14,165,233,0)' },
            ]),
          },
        },
      ],
    });

    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(trendEl);
    return () => {
      resizeObserver.disconnect();
      chart.dispose();
    };
  }, [data.progressData]);

  useEffect(() => {
    const radarEl = radarRef.current;
    if (!radarEl) return;

    const chart = echarts.init(radarEl, undefined, { renderer: 'canvas' });
    const radarValues = [
      data.radarData.questionActiveness,
      data.radarData.focus,
      data.radarData.thinking,
      data.radarData.logic,
      data.radarData.knowledge,
    ];
    chart.setOption({
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(15,23,42,0.92)',
        borderWidth: 0,
        textStyle: { color: '#fff', fontWeight: 700 },
      },
      radar: {
        center: ['50%', '54%'],
        radius: '70%',
        splitNumber: 5,
        axisName: { color: '#475569', fontWeight: 800, fontSize: 12 },
        axisLine: { lineStyle: { color: 'rgba(99,102,241,0.22)' } },
        splitLine: { lineStyle: { color: 'rgba(99,102,241,0.18)' } },
        splitArea: {
          areaStyle: {
            color: ['rgba(238,242,255,0.68)', 'rgba(252,231,243,0.36)'],
          },
        },
        indicator: [
          { name: t('admin.report.radarLabels.questionActiveness'), max: 100 },
          { name: t('admin.report.radarLabels.focus'), max: 100 },
          { name: t('admin.report.radarLabels.thinking'), max: 100 },
          { name: t('admin.report.radarLabels.logic'), max: 100 },
          { name: t('admin.report.radarLabels.knowledge'), max: 100 },
        ],
      },
      series: [{
        name: t('admin.report.aiDiagnosis'),
        type: 'radar',
        data: [{
          value: radarValues,
          name: t('admin.report.currentProfile'),
          symbol: 'circle',
          symbolSize: 7,
          lineStyle: { width: 4, color: '#ec4899' },
          itemStyle: { color: '#ec4899', borderColor: '#fff', borderWidth: 2 },
          areaStyle: {
            color: new echarts.graphic.RadialGradient(0.5, 0.5, 0.9, [
              { offset: 0, color: 'rgba(236,72,153,0.34)' },
              { offset: 1, color: 'rgba(14,165,233,0.15)' },
            ]),
          },
        }],
      }],
    });

    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(radarEl);
    return () => {
      resizeObserver.disconnect();
      chart.dispose();
    };
  }, [data.radarData]);

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
      <div className="relative overflow-hidden rounded-[28px] border border-pink-100 bg-white/85 p-5 shadow-sm lg:col-span-3">
        <div className="absolute -right-10 -top-12 h-36 w-36 rounded-full bg-pink-200/40 blur-3xl"></div>
        <div className="relative mb-2 flex items-center justify-between">
          <div>
            <p className="text-xs font-black uppercase tracking-[0.18em] text-pink-400">Energy Trend</p>
            <h3 className="mt-1 text-lg font-black text-gray-800">{t('admin.report.scoreTrend')}</h3>
          </div>
          <span className="rounded-full bg-pink-50 px-3 py-1 text-xs font-bold text-pink-600">{t('admin.report.weekly')}</span>
        </div>
        <div ref={trendRef} className="h-72 w-full" />
      </div>

      <div className="relative overflow-hidden rounded-[28px] border border-indigo-100 bg-white/85 p-5 shadow-sm lg:col-span-2">
        <div className="absolute -left-10 -bottom-12 h-36 w-36 rounded-full bg-cyan-200/40 blur-3xl"></div>
        <div className="relative mb-2">
          <p className="text-xs font-black uppercase tracking-[0.18em] text-indigo-400">Learning Profile</p>
          <h3 className="mt-1 text-lg font-black text-gray-800">{t('admin.report.aiDiagnosis')}</h3>
        </div>
        <div ref={radarRef} className="h-72 w-full" />
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const appDialog = useAppDialog();
  const apiBaseUrl = API_BASE;
  // 核心状态
  const [activeTab, setActiveTab] = useState('task');
  const [isLoading, setIsLoading] = useState(false);
  const [selectedPushTopicId, setSelectedPushTopicId] = useState('');
  const [knowledgeTopics, setKnowledgeTopics] = useState<{ topicId: string; title: string }[]>([]);
  const [subjectModalOpen, setSubjectModalOpen] = useState(false);
  const [subjectModalMode, setSubjectModalMode] = useState<SubjectModalMode>('create');
  const [editingSubject, setEditingSubject] = useState<GraphTopic | null>(null);
  const [subjectName, setSubjectName] = useState('');
  const [pendingResourceFiles, setPendingResourceFiles] = useState<File[]>([]);
  const [existingSubjectResources, setExistingSubjectResources] = useState<TopicResource[]>([]);
  const [modalDragging, setModalDragging] = useState(false);
  const [modalSaving, setModalSaving] = useState(false);
  const [modalResourceLoading, setModalResourceLoading] = useState(false);
  const [deletingSubjectId, setDeletingSubjectId] = useState('');
  const [deletingResourceId, setDeletingResourceId] = useState('');
  const [allResources, setAllResources] = useState<TopicResource[]>([]);
  const modalFileInputRef = useRef<HTMLInputElement>(null);

  // 后端真实数据
  const [learningData, setLearningData] = useState({
    todayStar: 0,
    todayStarIncrease: 0,
    focusTime: 0,
    questionActiveness: t('admin.report.activenessLabels.pending'),
    progressData: [] as { day: string, score: number }[],
    radarData: {
      questionActiveness: 0,
      focus: 0,
      thinking: 0,
      logic: 0,
      knowledge: 0
    }
  });
  const [knowledgePoints, setKnowledgePoints] = useState<{ id: number, topicId: string, name: string, lastReview: string, resourceCount: number }[]>([]);
  const [engineLogs, setEngineLogs] = useState<string[]>([]);
  const [dataLoading, setDataLoading] = useState(false);
  // 知识图谱状态
  const [graphNodes, setGraphNodes] = useState<GraphTopic[]>([]);
  const [selectedNode, setSelectedNode] = useState<GraphTopic | null>(null);
  const [selectedGraphRootId, setSelectedGraphRootId] = useState('');
  const [graphExpanded, setGraphExpanded] = useState(false);

  // 页面加载时自动获取后端数据
  useEffect(() => {
    fetchAllData();
  }, [activeTab]);

  // ================= 🌟 最终版：完整显示周一到周日七天，100%真实计算 =================
  const fetchAllData = async () => {
    setDataLoading(true);
    try {
      // 1. 获取当前状态
      const stateRes = await fetch(`${apiBaseUrl}/session/state`);
      let stateData: any = null;
      if (stateRes.ok) {
        stateData = await stateRes.json();
      }

      // 2. 获取所有事件历史，用于计算真实数据
      const eventsRes = await fetch(`${apiBaseUrl}/session/events`);
      let eventsData: any = null;
      if (eventsRes.ok) {
        eventsData = await eventsRes.json();
      }

      const graphRes = await fetch(`${apiBaseUrl}/knowledge/graph`);
      if (graphRes.ok) {
        const graphData = await graphRes.json();
        // 原来的处理逻辑
        const topics = ((graphData.topics || []) as GraphTopic[]).map((topic) => ({
          topicId: topic.topic_id,
          title: topic.title,
        }));
        setKnowledgeTopics(topics);
        setSelectedPushTopicId((prev) => topics.some((topic: { topicId: string }) => topic.topicId === prev) ? prev : (topics[0]?.topicId || ''));
        
        // 【新增】保存完整的知识图谱节点，供右侧渲染使用
        setGraphNodes(graphData.topics || []);
      }

      try {
        const resRes = await ResourceAPI.listResources();
        setAllResources(resRes.data || []);
      } catch { /* listResources pre-existing */ }

      // ================= 真实计算开始 =================
      if (stateData && eventsData) {
        const events = eventsData.events || [];
        const today = new Date().toDateString();
        
        // 筛选今日事件
        const todayEvents = events.filter((event: any) => 
          new Date(event.ts).toDateString() === today
        );

        // 计算今日新增星星
        let todayIncrease = 0;
        const scoreEvents = todayEvents.filter((e: any) => e.kind === 'score_change');
        scoreEvents.forEach((e: any) => {
          todayIncrease += e.payload.delta || 0;
        });

        // 计算专注时长（基于今日事件的时间跨度）
        let focusMinutes = 0;
        if (todayEvents.length > 0) {
          const firstEvent = new Date(todayEvents[0].ts);
          const lastEvent = new Date(todayEvents[todayEvents.length - 1].ts);
          focusMinutes = Math.floor((lastEvent.getTime() - firstEvent.getTime()) / 1000 / 60);
          if (focusMinutes < 0) focusMinutes = 0;
          if (focusMinutes === 0 && todayEvents.length > 0) focusMinutes = 5; // 至少5分钟
        }

        // 计算提问积极性（基于今日用户输入次数）
        const userInputCount = todayEvents.filter((e: any) => 
          e.kind === 'user_input' || e.kind === 'user_audio'
        ).length;
        let activenessLabel = t('admin.report.activenessLabels.good');
        if (userInputCount >= 10) activenessLabel = t('admin.report.activenessLabels.excellent');
        else if (userInputCount >= 5) activenessLabel = t('admin.report.activenessLabels.good');
        else if (userInputCount >= 1) activenessLabel = t('admin.report.activenessLabels.fair');
        else activenessLabel = t('admin.report.activenessLabels.toObserve');

        // ================= 🌟 最终修复：完整显示周一到周日七天，再也不会少任何一天 =================
        // 固定显示完整一周七天
        const weekDays = [
          t('admin.report.days.monday'),
          t('admin.report.days.tuesday'),
          t('admin.report.days.wednesday'),
          t('admin.report.days.thursday'),
          t('admin.report.days.friday'),
          t('admin.report.days.saturday'),
          t('admin.report.days.sunday'),
        ];
        // 初始化所有七天，默认得分0，确保100%显示，不会丢失任何一天
        const dailyScores: Record<string, number> = {};
        weekDays.forEach(d => { dailyScores[d] = 0; });

        // 🌟 100%正确的周几映射：JS里getDay() 0=周日，1=周一，2=周二，3=周三，4=周四，5=周五，6=周六
        events.forEach((event: any) => {
          if (event.kind === 'score_change') {
            const eventDate = new Date(event.ts);
            const eventDayNum = eventDate.getDay();
            const dayIdx = eventDayNum === 0 ? 6 : eventDayNum - 1; // 0=Sun→6, 1=Mon→0, ...
            const dayName = weekDays[dayIdx] || '';

            // 统计所有七天的得分
            if (dayName && dayName in dailyScores) {
              dailyScores[dayName] += event.payload.delta || 0;
            }
          }
        });

        // 转换为固定顺序的数组，确保周一到周日顺序不变
        const progressData = weekDays.map(day => ({
          day,
          score: Math.max(0, dailyScores[day])
        }));

        // 计算雷达图数据（基于现有数据估算）
        const consecutiveCorrect = stateData.learning?.consecutive_correct || 0;
        const radarData = {
          questionActiveness: Math.min(100, userInputCount * 10),
          focus: Math.min(100, focusMinutes * 2),
          thinking: Math.min(100, (consecutiveCorrect * 20) + 20),
          logic: Math.min(100, (consecutiveCorrect * 15) + 30),
          knowledge: Math.min(100, (stateData.learning?.total_score || 0) / 2)
        };

        // 更新状态
        setLearningData({
          todayStar: stateData.learning?.total_score || 0,
          todayStarIncrease: todayIncrease,
          focusTime: focusMinutes,
          questionActiveness: activenessLabel,
          progressData,
          radarData
        });
      }

      // 3. 获取错题本数据
      const reviewRes = await fetch(`${apiBaseUrl}/session/review-queue`);
      if (reviewRes.ok) {
        const reviewData = await reviewRes.json();
        setKnowledgePoints(
          (reviewData.items || []).map((item: any, idx: number) => ({
            id: idx + 1,
            topicId: item.topic_id,
            name: item.title,
            lastReview: new Date().toLocaleString(),
            resourceCount: item.resource_count || 0,
          })) || []
        );
      }

      // 4. 获取引擎日志
      if (eventsData) {
        setEngineLogs(
          eventsData.events?.slice(-20).map((event: any) => 
            `[${new Date(event.ts).toLocaleTimeString()}] ${event.kind}: ${JSON.stringify(event.payload)}`
          ) || []
        );
      }
    } catch (error) {
      console.error("获取数据失败", error);
    } finally {
      setDataLoading(false);
    }
  };

  // 文件校验逻辑
  const validateResourceFile = (file: File) => {
    const allowedTypes = [
      'video/mp4', 'video/mpeg', 'video/avi', 'video/mov', 'video/quicktime',
      'audio/mpeg', 'audio/wav', 'audio/x-wav', 'audio/mp4', 'audio/aac', 'audio/ogg',
      'image/jpeg', 'image/jpg', 'image/png', 'image/gif',
      'application/pdf', 'text/plain',
      'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    ];
    const allowedExtensions = ['.mp4', '.mpeg', '.avi', '.mov', '.mp3', '.wav', '.m4a', '.aac', '.ogg', '.jpg', '.jpeg', '.png', '.gif', '.pdf', '.txt', '.doc', '.docx', '.ppt', '.pptx'];
    const lowerName = file.name.toLowerCase();
    const isAllowed = allowedTypes.includes(file.type) || allowedExtensions.some((ext) => lowerName.endsWith(ext));

    if (!isAllowed) {
      void appDialog.alert(t('admin.subject.fileFormatUnsupported'), { title: t('admin.subject.fileFormatTitle'), intent: 'warning' });
      return false;
    }

    if (file.size > 500 * 1024 * 1024) {
      void appDialog.alert(t('admin.subject.fileTooLarge'), { title: t('admin.subject.fileTooLargeTitle'), intent: 'warning' });
      return false;
    }

    return true;
  };

  const addResourceFiles = (files: FileList | File[] | null) => {
    if (!files) return;
    const validFiles = Array.from(files).filter(validateResourceFile);
    if (validFiles.length === 0) return;

    setPendingResourceFiles((prev) => {
      const existingKeys = new Set(prev.map((file) => `${file.name}-${file.size}-${file.lastModified}`));
      const nextFiles = validFiles.filter((file) => !existingKeys.has(`${file.name}-${file.size}-${file.lastModified}`));
      return [...prev, ...nextFiles];
    });
  };

  const handleModalFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    addResourceFiles(e.target.files);
    e.target.value = '';
  };

  const handleModalDragEnter = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setModalDragging(true);
  };

  const handleModalDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setModalDragging(true);
  };

  const handleModalDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setModalDragging(false);
  };

  const handleModalDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setModalDragging(false);
    addResourceFiles(e.dataTransfer.files);
  };

  const resetSubjectModal = () => {
    setSubjectModalMode('create');
    setEditingSubject(null);
    setSubjectName('');
    setPendingResourceFiles([]);
    setExistingSubjectResources([]);
    setModalDragging(false);
    setModalResourceLoading(false);
    setDeletingResourceId('');
  };

  const openCreateSubjectModal = () => {
    resetSubjectModal();
    setSubjectModalOpen(true);
  };

  const openEditSubjectModal = async (topic: GraphTopic) => {
    resetSubjectModal();
    setSubjectModalMode('edit');
    setEditingSubject(topic);
    setSubjectName(topic.title);
    setSubjectModalOpen(true);
    setModalResourceLoading(true);
    try {
      const res = await ResourceAPI.getTopicResources(topic.topic_id);
      setExistingSubjectResources((res.data?.resources || []) as TopicResource[]);
    } catch (error) {
      console.error('加载资源失败', error);
      setExistingSubjectResources([]);
    } finally {
      setModalResourceLoading(false);
    }
  };

  const closeSubjectModal = () => {
    if (modalSaving) return;
    setSubjectModalOpen(false);
    resetSubjectModal();
  };

  const pollResourceIngestion = (resourceId: string) => {
    const intervalId = window.setInterval(async () => {
      try {
        const statusRes = await ResourceAPI.getResourceIngestionStatus(resourceId);
        const status = statusRes.data?.status;
        const err = statusRes.data?.error || '';
        if (status === 'failed' && err.includes('LLM not configured')) {
          window.clearInterval(intervalId);
          await appDialog.alert(LLM_NOT_CONFIGURED_MESSAGE, { title: t('admin.settings.notConfigured'), intent: 'warning' });
          void fetchAllData();
          return;
        }
        if (status === 'processing') {
          void fetchGraphData();
          void fetchAllData(); // also refresh resources to get progress labels
        }
        if (status === 'completed' || status === 'failed') {
          window.clearInterval(intervalId);
          void fetchAllData();
        }
      } catch (error) {
        console.error('轮询资源解析状态失败', error);
        window.clearInterval(intervalId);
      }
    }, 5000);
  };

  const fetchGraphData = async () => {
    try {
      const graphRes = await fetch(`${apiBaseUrl}/knowledge/graph`);
      if (graphRes.ok) {
        const graphData = await graphRes.json();
        const newTopics: GraphTopic[] = graphData.topics || [];
        const serialize = (items: GraphTopic[]) => items
          .map((topic) => `${topic.topic_id}|${topic.title}|${(topic.parent_ids || []).slice().sort().join(',')}|${(topic.prerequisite_ids || []).slice().sort().join(',')}`)
          .sort()
          .join('||');
        const oldSignature = serialize(graphNodes);
        const newSignature = serialize(newTopics);
        if (oldSignature !== newSignature) {
          setGraphNodes(newTopics);
        }
      }
    } catch { /* ignore */ }
  };

  const uploadPendingFilesForSubject = async (topicId: string, tags: string[], files: File[] = pendingResourceFiles) => {
    const subject = getSubjectTag(tags);
    const languageId = getSubjectLanguageId(tags);
    for (const file of files) {
      const res = await ResourceAPI.uploadResource({
        file,
        topicId,
        resourceName: stripFileExtension(file.name),
        category: 'learn',
        subject: subject || undefined,
        languageId: languageId || undefined,
      });
      const resourceId = res.data?.resource?.resource_id;
      if (resourceId) pollResourceIngestion(resourceId);
    }
  };

  const startSubjectUploads = (topicId: string, tags: string[], files: File[]) => {
    if (files.length === 0) return;
    void uploadPendingFilesForSubject(topicId, tags, files)
      .then(() => fetchAllData())
      .catch(async (error) => {
        console.error('学科资源上传失败', error);
        if (isLlmNotConfiguredError(error)) {
          await appDialog.alert(LLM_NOT_CONFIGURED_MESSAGE, { title: t('admin.settings.notConfigured'), intent: 'warning' });
          return;
        }
        await appDialog.alert(t('admin.subject.uploadFailed'), { title: t('admin.subject.uploadFailedTitle'), intent: 'error' });
      });
  };

  const handleSaveSubject = async () => {
    const normalizedName = subjectName.trim();
    if (!normalizedName) {
      await appDialog.alert(t('admin.subject.nameRequired'), { title: t('admin.subject.nameMissing'), intent: 'warning' });
      return;
    }

    setModalSaving(true);
    try {
      let topicId = editingSubject?.topic_id || '';
      let tags = editingSubject?.tags || [];
      const filesToUpload = [...pendingResourceFiles];

      if (subjectModalMode === 'create') {
        const res = await KnowledgeAPI.createSubject(normalizedName);
        topicId = res.data?.topic_id;
        tags = res.data?.tags || [];
      } else if (editingSubject && normalizedName !== editingSubject.title) {
        const res = await KnowledgeAPI.updateSubject(editingSubject.topic_id, normalizedName);
        topicId = res.data?.topic_id || editingSubject.topic_id;
        tags = res.data?.tags || editingSubject.tags || [];
      }

      if (!topicId) throw new Error('学科创建失败');

      setSubjectModalOpen(false);
      resetSubjectModal();
      void fetchAllData();
      startSubjectUploads(topicId, tags, filesToUpload);
    } catch (error) {
      console.error('保存学科失败', error);
      if (isLlmNotConfiguredError(error)) {
        await appDialog.alert(LLM_NOT_CONFIGURED_MESSAGE, { title: t('admin.settings.notConfigured'), intent: 'warning' });
        return;
      }
      await appDialog.alert(t('admin.subject.saveFailed'), { title: t('admin.subject.saveFailedTitle'), intent: 'error' });
    } finally {
      setModalSaving(false);
    }
  };

  const handleDeleteSubject = async (topic: GraphTopic) => {
    if (!(await appDialog.confirm(t('admin.confirm.deleteSubject', { title: topic.title }), { title: t('admin.subject.deleteSubject'), intent: 'danger', confirmText: t('common.delete') }))) return;

    setDeletingSubjectId(topic.topic_id);
    try {
      await KnowledgeAPI.deleteSubject(topic.topic_id);
      if (editingSubject?.topic_id === topic.topic_id) closeSubjectModal();
      await fetchAllData();
    } catch (error) {
      console.error('删除学科失败', error);
      await appDialog.alert(t('admin.subject.deleteFailed'), { title: t('admin.subject.deleteFailedTitle'), intent: 'error' });
    } finally {
      setDeletingSubjectId('');
    }
  };

  const handleDeleteExistingResource = async (resource: TopicResource) => {
    if (!(await appDialog.confirm(t('admin.confirm.deleteResource', { title: resource.resource_name }), { title: t('admin.subject.deleteResource'), intent: 'danger', confirmText: t('common.delete') }))) return;

    setDeletingResourceId(resource.resource_id);
    try {
      await ResourceAPI.deleteResource(resource.resource_id);
      setExistingSubjectResources((prev) => prev.filter((item) => item.resource_id !== resource.resource_id));
      void fetchAllData();
    } catch (error) {
      console.error('删除资源失败', error);
      await appDialog.alert(t('admin.subject.deleteResourceFailed'), { title: t('admin.subject.deleteResourceFailedTitle'), intent: 'error' });
    } finally {
      setDeletingResourceId('');
    }
  };

  const subjectRoots = useMemo(
    () => graphNodes.filter((topic) => (topic.tags || []).includes('facet:root')),
    [graphNodes],
  );

  const getExtractedNodeCount = (rootId: string) => {
    let total = 0;
    for (const res of allResources) {
      if (res.topic_id !== rootId) continue;
      total += res.candidate_node_count ?? res.extracted_node_count ?? 0;
    }
    return total;
  };

  const getSubjectResourceCount = (rootId: string) => {
    return allResources.filter((res) => res.topic_id === rootId).length;
  };

  const getIngestionStageLabel = (rootId: string): string | null => {
    for (const res of allResources) {
      if (res.topic_id !== rootId) continue;
      if (res.ingestion_status !== 'processing') continue;
      return res.ingestion_stage || t('admin.resourceStatus.processing');
    }
    return null;
  };

  const getPipelineStageLabel = (rootId: string): string | null => {
    for (const res of allResources) {
      if (res.topic_id !== rootId) continue;
      if (res.ingestion_status === 'processing') {
        return pipelineStageToLabel(res.pipeline_stage);
      }
    }
    return null;
  };

  const pipelineStageToLabel = (stage?: string): string => {
    switch (stage) {
      case 'parsing': return t('admin.resourceStatus.parsing');
      case 'candidate_extraction': return t('admin.resourceStatus.candidateExtraction');
      case 'review': return t('admin.resourceStatus.reviewing');
      case 'compiling': return t('admin.resourceStatus.compiling');
      case 'completed': return t('admin.resourceStatus.completed');
      case 'failed': return t('admin.resourceStatus.failed');
      default: return t('admin.resourceStatus.waiting');
    }
  };

  const collectSubgraphIds = (rootId: string, topics: GraphTopic[]) => {
    const ids = new Set([rootId]);
    let changed = true;

    while (changed) {
      changed = false;
      for (const topic of topics) {
        if (ids.has(topic.topic_id)) continue;
        const isChild = (topic.parent_ids || []).some((id) => ids.has(id)) || (topic.prerequisite_ids || []).some((id) => ids.has(id));
        if (!isChild) continue;
        ids.add(topic.topic_id);
        changed = true;
      }
    }

    return ids;
  };

  useEffect(() => {
    if (selectedGraphRootId && !graphNodes.some((topic) => topic.topic_id === selectedGraphRootId)) {
      setSelectedGraphRootId('');
    }
  }, [graphNodes, selectedGraphRootId]);

  // 任务推送功能
  const handlePushTask = async () => {
    if (!selectedPushTopicId) {
      await appDialog.alert(t('admin.task.noNodeSelected'), { title: t('admin.task.noNodeTitle'), intent: 'warning' });
      return;
    }
    setIsLoading(true);
    try {
      const res = await fetch(`${apiBaseUrl}/session/review/push`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic_id: selectedPushTopicId })
      });
      if (res.ok) {
        await appDialog.alert(t('admin.task.pushSuccess'), { title: t('admin.task.pushSuccessTitle'), intent: 'success' });
        fetchAllData();
      } else {
        await appDialog.alert(t('admin.task.pushFailed'), { title: t('admin.task.pushFailedTitle'), intent: 'error' });
      }
    } catch (error) {
      console.error(error);
      await appDialog.alert(t('admin.task.connectionFailed'), { title: t('admin.task.connectionFailedTitle'), intent: 'error' });
    } finally {
      setIsLoading(false);
    }
  };

  const mistakeTopicIds = knowledgePoints.map((item) => item.topicId);
  const visibleGraphNodes = useMemo(() => {
    if (!selectedGraphRootId) return graphNodes;
    const visibleGraphIds = collectSubgraphIds(selectedGraphRootId, graphNodes);
    return graphNodes.filter((node) => visibleGraphIds.has(node.topic_id));
  }, [graphNodes, selectedGraphRootId]);
  const visibleGraphEdgeCount = useMemo(
    () => visibleGraphNodes.reduce(
      (sum, node) => sum + (node.parent_ids?.length || 0) + (node.prerequisite_ids?.length || 0),
      0,
    ),
    [visibleGraphNodes],
  );
  const selectedGraphRoot = subjectRoots.find((topic) => topic.topic_id === selectedGraphRootId);
  const knowledgePointByTopicId = useMemo(
    () => new Map<string, GraphCanvasSelectionMeta>(
      knowledgePoints.map((point) => [point.topicId, {
        resourceCount: point.resourceCount || 0,
        mistakeCount: 1,
        lastReview: point.lastReview || null,
      }]),
    ),
    [knowledgePoints],
  );

  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setGraphExpanded(false);
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-50 to-pink-50 p-6">
      {/* 顶部导航 */}
      <div className="max-w-5xl mx-auto mb-6">
        <div className="bg-white/80 backdrop-blur rounded-2xl p-4 shadow-sm flex justify-between items-center">
          <button 
            onClick={() => navigate('/')}
            className="flex items-center gap-2 text-gray-700 hover:text-gray-900 cursor-pointer"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            <span className="text-lg font-medium">{t('common.backToHall')}</span>
          </button>
          <h1 className="text-lg font-semibold">{t('admin.title')}</h1>
          <div className="flex items-center gap-3">
            <LanguageSwitcher />
            <div className="w-8"></div>
          </div>
        </div>
      </div>

      {/* 标签页导航 */}
      <div className="max-w-5xl mx-auto mb-6 bg-white/80 backdrop-blur rounded-2xl shadow-sm">
        <div className="flex border-b border-gray-100">
          <button
            onClick={() => setActiveTab('task')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'task' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            📁 {t('admin.tabs.task')}
          </button>
          <button
            onClick={() => setActiveTab('report')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'report' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            📊 {t('admin.tabs.report')}
          </button>
          <button
            onClick={() => setActiveTab('mistake')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'mistake' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            📝 {t('admin.tabs.mistake')}
          </button>
          <button
            onClick={() => setActiveTab('graph')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'graph' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            🕸️ {t('admin.tabs.graph')}
          </button>
          <button
            onClick={() => setActiveTab('debug')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'debug' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            ⚙️ {t('admin.tabs.debug')}
          </button>
          <button
            onClick={() => setActiveTab('settings')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'settings' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            🔧 {t('admin.tabs.settings')}
          </button>
        </div>
      </div>

      {/* 标签页内容 */}
      <div className={`${activeTab === 'graph' ? 'max-w-7xl' : 'max-w-5xl'} mx-auto`}>
        {/* 1. 任务配置 */}
        {activeTab === 'task' && (
          <div className="bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm space-y-6">
            <div>
              <div className="mb-5 flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-xl font-black text-gray-800">{t('admin.subject.title')}</h2>
                  <p className="mt-1 text-xs text-gray-400">{t('admin.subject.description')}</p>
                </div>
                <span className="rounded-full border border-pink-100 bg-pink-50 px-3 py-1 text-xs font-semibold text-pink-600">
                  {t('admin.subject.count', { count: subjectRoots.length })}
                </span>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {subjectRoots.map((root) => {
                  const nodeCount = getExtractedNodeCount(root.topic_id);
                  const resourceCount = getSubjectResourceCount(root.topic_id);
                  const isDeleting = deletingSubjectId === root.topic_id;
                  return (
                    <div
                      key={root.topic_id}
                      onClick={() => void openEditSubjectModal(root)}
                      className="group relative min-h-[180px] cursor-pointer overflow-hidden rounded-[28px] border-2 border-solid border-pink-200 bg-gradient-to-br from-white via-rose-50/80 to-amber-50 p-5 shadow-sm transition-all hover:-translate-y-0.5 hover:border-pink-300 hover:shadow-xl"
                    >
                      <div className="absolute -right-10 -top-12 h-32 w-32 rounded-full bg-pink-200/30 blur-2xl transition-transform group-hover:scale-125"></div>
                      <div className="relative flex items-start justify-between gap-3">
                        <div className="pt-1">
                          <span className="rounded-full bg-white/80 px-2.5 py-1 text-[11px] font-bold text-pink-500 shadow-sm">{t('admin.subject.configured')}</span>
                          <h3 className="mt-4 max-w-[14rem] truncate text-2xl font-black tracking-tight text-gray-800">{root.title}</h3>
                        </div>
                        <div className="flex shrink-0 gap-2">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              void openEditSubjectModal(root);
                            }}
                            className="rounded-full border border-pink-100 bg-white/90 p-2 text-gray-500 shadow-sm transition-colors hover:border-pink-200 hover:text-pink-600"
                            aria-label={`编辑${root.title}`}
                          >
                            <Pencil size={16} />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              void handleDeleteSubject(root);
                            }}
                            disabled={isDeleting}
                            className="rounded-full border border-red-100 bg-white/90 p-2 text-gray-400 shadow-sm transition-colors hover:border-red-200 hover:text-red-500 disabled:opacity-50"
                            aria-label={`删除${root.title}`}
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </div>

                      <div className="relative mt-8 grid grid-cols-3 gap-2 text-xs text-gray-500">
                        <div className="rounded-2xl border border-white/80 bg-white/70 p-2">
                          <p className="font-bold text-gray-700">{nodeCount}</p>
                          <p>{t('admin.subject.nodes')}</p>
                        </div>
                        <div className="rounded-2xl border border-white/80 bg-white/70 p-2">
                          <p className="font-bold text-gray-700">{resourceCount}</p>
                          <p>{t('admin.subject.resourceCount')}</p>
                          {(() => { const label = getPipelineStageLabel(root.topic_id); return label ? <p className="mt-0.5 text-[10px] text-amber-600 font-semibold">{label}</p> : getIngestionStageLabel(root.topic_id) ? <p className="mt-0.5 text-[10px] text-amber-600 font-semibold">{getIngestionStageLabel(root.topic_id)}</p> : null; })()}
                        </div>
                        <div className="rounded-2xl border border-white/80 bg-white/70 p-2">
                          <p className="font-bold text-gray-700">{getSubjectTag(root.tags || []) || 'custom'}</p>
                          <p>{t('admin.subject.subjectTag')}</p>
                        </div>
                      </div>
                    </div>
                  );
                })}

                <button
                  type="button"
                  onClick={openCreateSubjectModal}
                  className="group flex min-h-[180px] items-center justify-center rounded-[28px] border-2 border-dashed border-pink-200 bg-white/65 p-5 text-center shadow-sm transition-all hover:-translate-y-0.5 hover:border-pink-400 hover:bg-pink-50/60 hover:shadow-xl"
                >
                  <div className="flex flex-col items-center gap-3">
                    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-pink-500 to-rose-400 text-white shadow-lg shadow-pink-200 transition-transform group-hover:scale-110">
                      <Plus size={34} strokeWidth={2.8} />
                    </div>
                    <div>
                      <p className="text-base font-black text-gray-800">{t('admin.subject.newSubject')}</p>
                      <p className="mt-1 text-xs text-gray-400">{t('admin.subject.newSubjectDesc')}</p>
                    </div>
                  </div>
                </button>
              </div>
            </div>

            {allResources.length > 0 && (
              <div className="rounded-[24px] border border-gray-100 bg-white/70 p-5">
                <h2 className="text-sm font-black text-gray-700 mb-4">{t('admin.resourceStatus.title')}</h2>
                <div className="space-y-2 max-h-80 overflow-y-auto">
                  {allResources.map((res) => {
                    const status = res.ingestion_status || 'unknown';
                    const isProcessing = status === 'processing';
                    const isCompleted = status === 'completed';
                    const isFailed = status === 'failed';
                    return (
                    <div key={res.resource_id} className={[
                      'flex items-center gap-3 rounded-2xl border px-4 py-3',
                      isProcessing ? 'border-amber-100 bg-amber-50/50' :
                      isCompleted ? 'border-green-100 bg-green-50/40' :
                      isFailed ? 'border-red-100 bg-red-50/40' :
                      'border-gray-100 bg-white'
                    ].join(' ')}>
                      <div className={[
                        'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl',
                        isProcessing ? 'bg-amber-100' :
                        isCompleted ? 'bg-green-100' :
                        isFailed ? 'bg-red-100' :
                        'bg-gray-100'
                      ].join(' ')}>
                        {isProcessing ? (
                          <Loader2 size={18} className="animate-spin text-amber-600" />
                        ) : isCompleted ? (
                          <CheckCircle2 size={18} className="text-green-600" />
                        ) : isFailed ? (
                          <AlertCircle size={18} className="text-red-500" />
                        ) : (
                          <Clock size={18} className="text-gray-400" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-bold text-gray-800">{res.resource_name}</p>
                        <p className="text-xs text-gray-400">
                          {isProcessing && (res.pipeline_stage ? `${pipelineStageToLabel(res.pipeline_stage)} · ` : res.ingestion_stage ? `${res.ingestion_stage} · ` : '')}
                          {res.media_type && `${res.media_type} `}
                          {res.size_bytes && ` ${(res.size_bytes / 1024 / 1024).toFixed(2)} MB`}
                          {res.extracted_node_count !== undefined && res.extracted_node_count > 0 && <>{` · ${t('admin.resourceStatus.candidateNodes')} ${res.extracted_node_count}`}</>}
                        </p>
                      </div>
                      <span className={[
                        'shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold',
                        isProcessing ? 'bg-amber-100 text-amber-700' :
                        isCompleted ? 'bg-green-100 text-green-700' :
                        isFailed ? 'bg-red-100 text-red-700' :
                        'bg-gray-100 text-gray-500'
                      ].join(' ')}>
                        {isProcessing ? pipelineStageToLabel(res.pipeline_stage || 'parsing') : isCompleted ? t('admin.resourceStatus.completed') : isFailed ? t('admin.resourceStatus.failed') : t('admin.resourceStatus.waiting')}
                      </span>
                    </div>
                  )})}
                </div>
              </div>
            )}

            <div className="rounded-[24px] border border-gray-100 bg-white/70 p-5">
              <h2 className="text-lg font-semibold text-gray-700 mb-4">{t('admin.task.title')}</h2>
              <div className="mb-3">
                <label className="text-sm text-gray-500 mb-1 block">{t('admin.task.label')}</label>
                <select
                  value={selectedPushTopicId}
                  onChange={(e) => setSelectedPushTopicId(e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-200"
                >
                  <option value="">{t('admin.task.placeholder')}</option>
                  {knowledgeTopics.map((topic) => (
                    <option key={topic.topicId} value={topic.topicId}>{topic.title}</option>
                  ))}
                </select>
              </div>
              <button
                onClick={handlePushTask}
                disabled={isLoading}
                className="w-full py-3 bg-gray-800 text-white font-bold rounded-lg disabled:opacity-50 cursor-pointer hover:bg-gray-700 transition-colors"
              >
                {isLoading ? t('admin.task.pushing') : t('admin.task.pushBtn')}
              </button>
            </div>

          </div>
        )}

        {/* 2. AI 学情报告（完整显示周一到周日七天） */}
        {activeTab === 'report' && (
          <div className="relative overflow-hidden rounded-[32px] border border-white/80 bg-white/80 p-6 shadow-sm backdrop-blur">
            <div className="pointer-events-none absolute -right-20 -top-24 h-56 w-56 rounded-full bg-pink-200/45 blur-3xl"></div>
            <div className="pointer-events-none absolute -left-24 bottom-8 h-56 w-56 rounded-full bg-sky-200/45 blur-3xl"></div>
            {dataLoading ? (
              <div className="relative text-center py-10 text-gray-500">{t('admin.report.loadingData')}</div>
            ) : (
              <div className="relative space-y-6">
                <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                  <div>
                    <p className="text-xs font-black uppercase tracking-[0.24em] text-pink-400">Learning Report</p>
                    <h2 className="mt-1 text-2xl font-black text-gray-900">{t('admin.report.title')}</h2>
                    <p className="mt-1 text-xs text-gray-500">{t('admin.report.subtitle')}</p>
                  </div>
                  <div className="rounded-full border border-pink-100 bg-white/80 px-4 py-2 text-xs font-bold text-pink-600 shadow-sm">
                    {t('admin.report.autoSync')}
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  <div className="relative overflow-hidden rounded-[26px] border border-pink-100 bg-gradient-to-br from-white to-pink-50 p-5 shadow-sm">
                    <div className="absolute right-4 top-4 h-12 w-12 rounded-2xl bg-pink-100"></div>
                    <p className="text-sm font-bold text-gray-500">{t('admin.report.todayStars')}</p>
                    <div className="mt-3 flex items-end gap-2">
                      <p className="text-4xl font-black text-gray-900">{learningData.todayStar}</p>
                      {learningData.todayStarIncrease > 0 && (
                        <span className="mb-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-black text-emerald-600">+{learningData.todayStarIncrease}</span>
                      )}
                    </div>
                    <p className="mt-2 text-xs text-gray-400">{t('admin.report.description')}</p>
                  </div>

                  <div className="relative overflow-hidden rounded-[26px] border border-sky-100 bg-gradient-to-br from-white to-sky-50 p-5 shadow-sm">
                    <div className="absolute right-4 top-4 h-12 w-12 rounded-2xl bg-sky-100"></div>
                    <p className="text-sm font-bold text-gray-500">{t('admin.report.focusTime')}</p>
                    <div className="mt-3 flex items-end gap-2">
                      <p className="text-4xl font-black text-gray-900">{learningData.focusTime}</p>
                      <span className="mb-1 text-sm font-black text-sky-600">{t('admin.report.minutes')}</span>
                    </div>
                    <p className="mt-2 text-xs text-gray-400">{learningData.focusTime > 0 ? t('admin.report.todayStudying') : t('admin.report.waitingEvents')}</p>
                  </div>

                  <div className="relative overflow-hidden rounded-[26px] border border-indigo-100 bg-gradient-to-br from-white to-indigo-50 p-5 shadow-sm">
                    <div className="absolute right-4 top-4 h-12 w-12 rounded-2xl bg-indigo-100"></div>
                    <p className="text-sm font-bold text-gray-500">{t('admin.report.questionActiveness')}</p>
                    <div className="mt-3 flex items-end gap-2">
                      <p className="text-4xl font-black text-gray-900">{learningData.questionActiveness}</p>
                      <span className="mb-1 text-xs font-black text-indigo-500">{t('admin.report.interactionProfile')}</span>
                    </div>
                    <p className="mt-2 text-xs text-gray-400">{t('admin.report.basedOnInputs')}</p>
                  </div>
                </div>

                <LearningReportCharts data={learningData} />
              </div>
            )}
          </div>
        )}

        {/* 3. 错题本与回放 (已重构版) */}
        {activeTab === 'mistake' && (
          <div className="h-[600px]">
            
            {/* 智能错题流 (重构排版) */}
            <div className="bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm flex flex-col h-full border-t-4 border-pink-400">
              <div className="flex items-center gap-2 mb-2">
                <BookOpen className="text-pink-500" size={24} />
                <h2 className="text-xl font-bold text-gray-800">{t('admin.mistake.title')}</h2>
              </div>
              <p className="text-xs text-gray-500 mb-6 pb-4 border-b border-gray-100">
                {t('admin.mistake.description')}
              </p>
              
              <div className="flex-1 overflow-y-auto space-y-4 pr-2 scrollbar-hide">
                {dataLoading ? (
                  <div className="text-center py-6 text-gray-400 animate-pulse">{t('admin.mistake.loading')}</div>
                ) : knowledgePoints.length === 0 ? (
                  <div className="text-center py-10 bg-gray-50 rounded-xl border border-dashed border-gray-200">
                    <span className="text-4xl block mb-2">🏆</span>
                    <p className="text-gray-500 font-medium">{t('admin.mistake.noMistakes')}</p>
                  </div>
                ) : (
                  knowledgePoints.map((kp) => (
                    <div key={kp.id} className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow relative overflow-hidden group">
                      <div className="absolute left-0 top-0 bottom-0 w-1.5 bg-gradient-to-b from-pink-300 to-pink-500"></div>
                      <div className="flex justify-between items-start mb-3">
                        <h3 className="font-bold text-gray-800 text-base">{kp.name}</h3>
                        <span className="bg-pink-50 text-pink-600 text-xs px-2 py-1 rounded-md font-medium flex items-center gap-1">
                          <AlertCircle size={12} /> {t('admin.mistake.toConquer')}
                        </span>
                      </div>
                      
                      <div className="grid grid-cols-2 gap-2 mb-4">
                        <div className="flex items-center gap-2 text-xs text-gray-500 bg-gray-50 p-2 rounded-lg">
                          <Video size={14} className="text-blue-400" />
                          <span>{t('admin.mistake.relatedVideo')} <strong className="text-gray-700">{kp.resourceCount}</strong></span>
                        </div>
                        <div className="flex items-center gap-2 text-xs text-gray-500 bg-gray-50 p-2 rounded-lg">
                          <Clock size={14} className="text-orange-400" />
                          <span className="truncate" title={kp.lastReview}>{t('admin.mistake.firstMistake')} {kp.lastReview.split(' ')[0]}</span>
                        </div>
                      </div>
                      
                      <button 
                        onClick={async () => {
                          try {
                            await fetch(`${apiBaseUrl}/session/review/push`, {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ topic_id: kp.topicId })
                            });
                            await appDialog.alert(t('admin.mistake.pushRetestSuccess'), { title: t('admin.task.pushSuccessTitle'), intent: 'success' });
                          } catch (e) {
                            await appDialog.alert(t('admin.mistake.pushRetestFailed'), { title: t('admin.task.pushFailedTitle'), intent: 'error' });
                          }
                        }}
                        className="w-full py-2.5 bg-gray-900 text-white text-sm font-bold rounded-lg hover:bg-pink-500 transition-colors cursor-pointer"
                      >
                        ⚡ {t('admin.mistake.pushRetest')}
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>

          </div>
        )}

        {/* 4. 知识图谱大屏 */}
        {activeTab === 'graph' && (
          <div className={graphExpanded ? 'fixed inset-0 z-40 p-4' : 'h-[760px]'}>
            {graphExpanded && <div className="absolute inset-0 bg-slate-950/70 backdrop-blur-sm"></div>}
            <div className={`relative flex h-full flex-col overflow-hidden border border-indigo-200/20 bg-slate-950 p-5 shadow-2xl shadow-indigo-950/20 ${graphExpanded ? 'rounded-[2.25rem]' : 'rounded-[2rem]'}`}>
              <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_15%_12%,rgba(244,114,182,0.23),transparent_28%),radial-gradient(circle_at_84%_18%,rgba(56,189,248,0.18),transparent_28%),linear-gradient(135deg,rgba(15,23,42,0.94),rgba(49,46,129,0.88))]"></div>
              <div className="relative mb-4 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="flex items-start gap-3">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white/10 text-cyan-200 ring-1 ring-white/15">
                    <Network size={23} />
                  </div>
                  <div>
                    <h2 className="text-xl font-black text-white">{t('admin.graph.title')}</h2>
                    <p className="mt-1 text-xs text-indigo-100/70">{t('admin.graph.description')}</p>
                  </div>
                </div>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                  <label className="flex items-center gap-2 rounded-2xl border border-white/10 bg-white/10 px-3 py-2 text-xs font-bold text-white/80">
                    {t('admin.graph.rootNode')}
                    <select
                      value={selectedGraphRootId}
                      onChange={(e) => {
                        setSelectedGraphRootId(e.target.value);
                        setSelectedNode(null);
                      }}
                      className="min-w-40 rounded-xl border border-white/10 bg-slate-950/80 px-3 py-1.5 text-xs text-white outline-none focus:ring-2 focus:ring-cyan-300/40"
                    >
                      <option value="">{t('admin.graph.allGraph')}</option>
                      {subjectRoots.map((root) => (
                        <option key={root.topic_id} value={root.topic_id}>{root.title}</option>
                      ))}
                    </select>
                  </label>
                  <div className="flex shrink-0 gap-2 text-[11px] font-bold text-white/80">
                    <span className="rounded-full border border-white/10 bg-white/10 px-3 py-1">{t('admin.graph.nodes', { count: visibleGraphNodes.length })}</span>
                    <span className="rounded-full border border-white/10 bg-white/10 px-3 py-1">{t('admin.graph.edges', { count: visibleGraphEdgeCount })}</span>
                    <button
                      type="button"
                      onClick={() => setGraphExpanded((current) => !current)}
                      className="inline-flex items-center gap-2 rounded-full border border-cyan-300/30 bg-cyan-400/12 px-3 py-1 text-[11px] font-extrabold text-cyan-50 transition hover:bg-cyan-400/18"
                    >
                      {graphExpanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
                      {graphExpanded ? t('admin.graph.exitFullscreen') : t('admin.graph.fullscreen')}
                    </button>
                  </div>
                </div>
              </div>

              {selectedGraphRoot && (
                <div className="relative mb-3 rounded-2xl border border-cyan-300/20 bg-cyan-400/10 px-4 py-2 text-xs font-semibold text-cyan-50">
                  {t('admin.graph.currentSubgraph', { title: selectedGraphRoot.title })}
                </div>
              )}

              <div className="relative flex-1 overflow-hidden rounded-[28px] border border-white/10 bg-slate-900/70 shadow-inner">
                <div className="pointer-events-none absolute inset-0 opacity-25 [background-image:linear-gradient(rgba(255,255,255,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.08)_1px,transparent_1px)] [background-size:28px_28px]"></div>
                {visibleGraphNodes.length === 0 ? (
                  <div className="relative flex h-full flex-col items-center justify-center text-center text-indigo-100/70">
                    <Network size={44} className="mb-3 text-indigo-200/60" />
                    <p className="text-sm font-bold">{t('admin.graph.generating')}</p>
                    <p className="mt-1 text-xs">{t('admin.graph.generatingHint')}</p>
                  </div>
                ) : (
                  <KnowledgeGraphCanvas
                    topics={visibleGraphNodes}
                    selectedTopicId={selectedNode?.topic_id}
                    mistakeTopicIds={mistakeTopicIds}
                    nodeMetaByTopicId={knowledgePointByTopicId}
                    onSelectNode={(node) => {
                      setSelectedNode(node);
                    }}
                  />
                )}

                <div className="pointer-events-none absolute bottom-4 left-4 flex flex-wrap gap-2 text-[11px] font-bold text-white/80">
                  <span className="rounded-full border border-pink-300/30 bg-pink-500/15 px-3 py-1">{t('admin.graph.legend.dashedParent')}</span>
                  <span className="rounded-full border border-cyan-300/30 bg-cyan-500/15 px-3 py-1">{t('admin.graph.legend.solidPrereq')}</span>
                  <span className="rounded-full border border-amber-300/30 bg-amber-500/15 px-3 py-1">{t('admin.graph.legend.yellowPath')}</span>
                  <span className="rounded-full border border-rose-300/30 bg-rose-500/15 px-3 py-1">{t('admin.graph.legend.pinkMistake')}</span>
                </div>

                {selectedNode && (
                  <div className="pointer-events-none absolute right-4 top-4 rounded-2xl border border-amber-300/20 bg-slate-950/72 px-4 py-3 text-[11px] font-semibold text-slate-100 shadow-lg shadow-slate-950/25 backdrop-blur">
                    {t('admin.graph.selectedNode', { title: selectedNode.title })}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* 5. 系统调试 */}
        {activeTab === 'debug' && (
          <div className="bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-700 mb-4">{t('admin.debug.title')}</h2>
            <p className="text-xs text-gray-400 mb-4">{t('admin.debug.description')}</p>
            {dataLoading ? (
              <div className="text-center py-6 text-gray-500">{t('admin.debug.loading')}</div>
            ) : (
              <div className="bg-gray-900 rounded-lg p-4 font-mono text-xs text-green-400 mb-6 max-h-60 overflow-y-auto">
                {engineLogs.length === 0 ? (
                  <p>[INFO] {t('admin.debug.noLogs')}</p>
                ) : (
                  engineLogs.map((log, i) => <p key={i}>{log}</p>)
                )}
              </div>
            )}
            <div className="bg-red-50 rounded-lg p-4 border border-red-200">
              <p className="text-sm text-red-600 font-medium mb-2">⚠️ {t('admin.debug.dangerZone')}</p>
              <p className="text-xs text-gray-500 mb-3">{t('admin.debug.dangerDescription')}</p>
              <button 
                onClick={async () => {
                  if(await appDialog.confirm(t('admin.debug.clearContextConfirm'), { title: t('admin.debug.clearContextTitle'), intent: 'danger', confirmText: t('common.clear') })) {
                    try {
                      await fetch(`${apiBaseUrl}/session/reset`, { method: "POST" });
                      await appDialog.alert(t('admin.debug.cleared'), { title: t('admin.debug.clearedTitle'), intent: 'success' });
                      fetchAllData();
                    } catch (e) {
                      await appDialog.alert(t('admin.debug.operationFailed'), { title: t('admin.debug.operationFailed'), intent: 'error' });
                    }
                  }
                }}
                className="bg-white text-gray-700 border border-gray-200 px-3 py-1 rounded text-xs hover:bg-gray-100 cursor-pointer"
              >
                {t('admin.debug.clearContext')}
              </button>
            </div>
          </div>
        )}
        {activeTab === 'settings' && <SettingsPanel />}
      </div>

      {subjectModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/45 p-4 backdrop-blur-sm"
          onMouseDown={closeSubjectModal}
        >
          <div
            className="w-full max-w-2xl overflow-hidden rounded-[32px] border border-white/70 bg-white shadow-2xl"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="relative overflow-hidden bg-gradient-to-br from-pink-500 via-rose-400 to-orange-300 p-6 text-white">
              <div className="absolute -right-12 -top-16 h-44 w-44 rounded-full bg-white/20 blur-2xl"></div>
              <div className="relative flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-bold uppercase tracking-[0.28em] text-white/75">Subject Studio</p>
                  <h2 className="mt-2 text-2xl font-black">
                    {subjectModalMode === 'create' ? t('admin.subject.newSubjectTitle') : t('admin.subject.editSubject')}
                  </h2>
                  <p className="mt-1 text-sm text-white/80">{t('admin.subject.subjectDesc')}</p>
                </div>
                <button
                  type="button"
                  onClick={closeSubjectModal}
                  disabled={modalSaving}
                  className="rounded-full bg-white/15 p-2 text-white transition-colors hover:bg-white/25 disabled:opacity-50"
                  aria-label="关闭弹窗"
                >
                  <X size={20} />
                </button>
              </div>
            </div>

            <div className="space-y-5 p-6">
              <div>
                <label className="mb-2 block text-sm font-bold text-gray-700">{t('admin.subject.subjectName')}</label>
                <input
                  type="text"
                  value={subjectName}
                  onChange={(e) => setSubjectName(e.target.value)}
                  placeholder={t('admin.subject.subjectNamePlaceholder')}
                  className="w-full rounded-2xl border border-pink-100 bg-pink-50/40 px-4 py-3 text-base font-semibold text-gray-800 shadow-inner outline-none transition-all placeholder:text-gray-400 focus:border-pink-300 focus:bg-white focus:ring-4 focus:ring-pink-100"
                />
              </div>

              <div className="rounded-[24px] border border-gray-200 bg-gray-50/80 p-4">
                <input
                  ref={modalFileInputRef}
                  type="file"
                  multiple
                  accept="video/*,audio/*,image/*,.pdf,.txt,.doc,.docx,.ppt,.pptx"
                  onChange={handleModalFileSelect}
                  className="hidden"
                />

                <div className="mb-3 flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-black text-gray-800">{t('admin.subject.resourceList')}</h3>
                    <p className="text-xs text-gray-400">{t('admin.subject.resourceHint')}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => modalFileInputRef.current?.click()}
                    className="flex h-10 w-10 items-center justify-center rounded-full bg-gray-900 text-white shadow-lg shadow-gray-200 transition-transform hover:scale-105"
                    aria-label="选择文件"
                  >
                    <Plus size={22} />
                  </button>
                </div>

                <div
                  onDragEnter={handleModalDragEnter}
                  onDragOver={handleModalDragOver}
                  onDragLeave={handleModalDragLeave}
                  onDrop={handleModalDrop}
                  className="relative min-h-[180px]"
                >
                  <div className={`max-h-72 space-y-2 overflow-y-auto pr-1 transition-all ${modalDragging ? 'blur-[2px]' : ''}`}>
                    {modalResourceLoading && (
                      <div className="rounded-2xl border border-dashed border-gray-200 bg-white p-5 text-center text-sm text-gray-400">
                        {t('admin.subject.loadingResources')}
                      </div>
                  )}

                  {!modalResourceLoading && existingSubjectResources.map((resource) => (
                    <div key={resource.resource_id} className="flex items-center justify-between gap-3 rounded-2xl border border-gray-100 bg-white px-4 py-3 shadow-sm">
                      <div className="flex min-w-0 items-center gap-3">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-pink-50 text-pink-500">
                          <FileText size={18} />
                        </div>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-bold text-gray-800">{resource.resource_name}</p>
                          <p className="text-xs text-gray-400">
                            {resource.media_type || 'file'} · {(resource.size_bytes / 1024 / 1024).toFixed(2)} MB · {resource.ingestion_status}
                          </p>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => void handleDeleteExistingResource(resource)}
                        disabled={deletingResourceId === resource.resource_id}
                        className="rounded-full p-2 text-gray-400 transition-colors hover:bg-red-50 hover:text-red-500 disabled:opacity-50"
                        aria-label={`删除资源${resource.resource_name}`}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  ))}

                  {pendingResourceFiles.map((file, index) => (
                    <div key={`${file.name}-${file.size}-${file.lastModified}`} className="flex items-center justify-between gap-3 rounded-2xl border border-amber-100 bg-amber-50/70 px-4 py-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white text-amber-500">
                          <FileText size={18} />
                        </div>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-bold text-gray-800">{file.name}</p>
                          <p className="text-xs text-amber-700/70">{t('admin.subject.pendingUploadLabel')} · {(file.size / 1024 / 1024).toFixed(2)} MB</p>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => setPendingResourceFiles((prev) => prev.filter((_, itemIndex) => itemIndex !== index))}
                        className="rounded-full p-2 text-amber-700/60 transition-colors hover:bg-white hover:text-amber-800"
                        aria-label={`移除待上传资源${file.name}`}
                      >
                        <X size={16} />
                      </button>
                    </div>
                  ))}

                  {!modalResourceLoading && existingSubjectResources.length === 0 && pendingResourceFiles.length === 0 && (
                    <div className="rounded-2xl border border-dashed border-gray-200 bg-white p-8 text-center">
                      <UploadCloud className="mx-auto text-gray-300" size={42} />
                      <p className="mt-3 text-sm font-semibold text-gray-500">{t('admin.subject.noResources')}</p>
                      <p className="mt-1 text-xs text-gray-400">{t('admin.subject.noResourcesHint')}</p>
                    </div>
                  )}
                </div>

                {modalDragging && (
                  <div className="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-[20px] border-2 border-dashed border-pink-300 bg-white/80 text-pink-600 shadow-2xl backdrop-blur-md">
                    <UploadCloud size={58} strokeWidth={1.8} />
                    <p className="mt-3 text-lg font-black">{t('admin.subject.dropImport')}</p>
                    <p className="mt-1 text-xs text-pink-400">{t('admin.subject.dropSupport')}</p>
                  </div>
                )}
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-gray-100 bg-gray-50 px-6 py-4">
              <p className="text-xs text-gray-400">
                {pendingResourceFiles.length > 0 ? t('admin.subject.pendingUpload', { count: pendingResourceFiles.length }) : t('admin.subject.saveHint')}
              </p>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={closeSubjectModal}
                  disabled={modalSaving}
                  className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-600 transition-colors hover:bg-gray-100 disabled:opacity-50"
                >
                  {t('common.cancel')}
                </button>
                <button
                  type="button"
                  onClick={() => void handleSaveSubject()}
                  disabled={modalSaving || !subjectName.trim()}
                  className="rounded-xl bg-gray-900 px-5 py-2 text-sm font-bold text-white shadow-lg shadow-gray-200 transition-colors hover:bg-pink-600 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {modalSaving ? t('admin.subject.saving') : subjectModalMode === 'create' ? t('admin.subject.createAndImport') : t('admin.subject.saveChanges')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
