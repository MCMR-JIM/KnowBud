import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import * as d3 from 'd3';
import type { SimulationLinkDatum, SimulationNodeDatum, ZoomTransform } from 'd3';
import * as echarts from 'echarts/core';
import { BarChart, LineChart, RadarChart } from 'echarts/charts';
import { GridComponent, LegendComponent, RadarComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { AlertCircle, BookOpen, CheckCircle2, Clock, FileText, Info, Loader2, Network, Pencil, Plus, Trash2, UploadCloud, Video, X } from 'lucide-react';
import { API_BASE } from '../api/config';
import { KnowledgeAPI, ResourceAPI } from '../api/client';
import { useAppDialog } from '../components/AppDialog';
import SettingsPanel from '../components/SettingsPanel';

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
  ingestion_status: string;
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
  radius: number;
  collisionRadius: number;
  topic: GraphTopic;
  isRoot: boolean;
  isMistake: boolean;
  subject: string;
  targetX?: number;
  targetY?: number;
  layoutDepth?: number;
};

type GraphCanvasLink = SimulationLinkDatum<GraphCanvasNode> & {
  source: string | GraphCanvasNode;
  target: string | GraphCanvasNode;
  type: 'parent' | 'prereq' | 'both';
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

function KnowledgeGraphCanvas({
  topics,
  selectedTopicId,
  mistakeTopicIds,
  onSelectNode,
}: {
  topics: GraphTopic[];
  selectedTopicId?: string;
  mistakeTopicIds: string[];
  onSelectNode: (topic: GraphTopic) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const onSelectNodeRef = useRef(onSelectNode);
  const selectedTopicIdRef = useRef(selectedTopicId);
  const redrawRef = useRef<(() => void) | null>(null);
  const mistakeKey = mistakeTopicIds.join('|');

  useEffect(() => {
    onSelectNodeRef.current = onSelectNode;
  }, [onSelectNode]);

  useEffect(() => {
    selectedTopicIdRef.current = selectedTopicId;
    redrawRef.current?.();
  }, [selectedTopicId]);

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
      const topicCount = Math.max(1, topics.length);
      const canvasSpan = Math.min(width, height);
      const nodes: GraphCanvasNode[] = topics.map((topic, index) => {
        const isRoot = (topic.tags || []).includes('facet:root');
        const edgeWeight = (topic.parent_ids?.length || 0) + (topic.prerequisite_ids?.length || 0);
        const angle = index * Math.PI * (3 - Math.sqrt(5));
        const initialRadius = canvasSpan * (0.14 + 0.38 * Math.sqrt((index + 1) / topicCount));
        const labelWidth = Math.min(172, Math.max(64, topic.title.length * 11 + 22));
        const nodeRadius = isRoot ? 18 : 9 + Math.min(edgeWeight * 2, 8);
        return {
          id: topic.topic_id,
          title: topic.title,
          topic,
          isRoot,
          isMistake: mistakeSet.has(topic.topic_id),
          subject: getSubjectTag(topic.tags || []) || 'general',
          radius: nodeRadius,
          collisionRadius: Math.max(nodeRadius + 30, labelWidth / 2 + 14),
          x: width / 2 + Math.cos(angle) * initialRadius,
          y: height / 2 + Math.sin(angle) * initialRadius,
        };
      });
      const linkByPair = new Map<string, GraphCanvasLink>();
      const upsertLink = (source: string, target: string, type: 'parent' | 'prereq') => {
        const key = `${source}->${target}`;
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

      const outgoing = new Map<string, string[]>();
      const incomingCount = new Map(nodes.map((node) => [node.id, 0]));
      for (const link of links) {
        const sourceId = String(link.source);
        const targetId = String(link.target);
        outgoing.set(sourceId, [...(outgoing.get(sourceId) || []), targetId]);
        incomingCount.set(targetId, (incomingCount.get(targetId) || 0) + 1);
      }

      const rootNodes = nodes.filter((node) => node.isRoot);
      const layoutRoots = (rootNodes.length ? rootNodes : nodes.filter((node) => (incomingCount.get(node.id) || 0) === 0)).slice();
      if (layoutRoots.length === 0 && nodes[0]) layoutRoots.push(nodes[0]);

      const depthById = new Map<string, number>();
      const rootById = new Map<string, string>();
      const queue: string[] = [];
      for (const root of layoutRoots) {
        depthById.set(root.id, 0);
        rootById.set(root.id, root.id);
        queue.push(root.id);
      }

      while (queue.length > 0) {
        const sourceId = queue.shift() || '';
        const nextDepth = (depthById.get(sourceId) || 0) + 1;
        for (const targetId of outgoing.get(sourceId) || []) {
          const currentDepth = depthById.get(targetId);
          if (currentDepth !== undefined && currentDepth >= nextDepth) continue;
          depthById.set(targetId, nextDepth);
          rootById.set(targetId, rootById.get(sourceId) || sourceId);
          queue.push(targetId);
        }
      }

      for (const node of nodes) {
        if (!rootById.has(node.id)) {
          rootById.set(node.id, node.id);
          depthById.set(node.id, 0);
          layoutRoots.push(node);
        }
      }

      const uniqueRootIds = Array.from(new Set(layoutRoots.map((root) => root.id)));
      const rootCenters = new Map<string, { x: number; y: number; angle: number }>();
      const rootOrbitX = width * 0.28;
      const rootOrbitY = height * 0.24;
      uniqueRootIds.forEach((rootId, index) => {
        const angle = uniqueRootIds.length === 1 ? -Math.PI / 2 : -Math.PI / 2 + (Math.PI * 2 * index) / uniqueRootIds.length;
        rootCenters.set(rootId, {
          x: uniqueRootIds.length === 1 ? width / 2 : width / 2 + Math.cos(angle) * rootOrbitX,
          y: uniqueRootIds.length === 1 ? height / 2 : height / 2 + Math.sin(angle) * rootOrbitY,
          angle,
        });
      });

      const groups = new Map<string, GraphCanvasNode[]>();
      for (const node of nodes) {
        const rootId = rootById.get(node.id) || node.id;
        const depth = depthById.get(node.id) || 0;
        node.layoutDepth = depth;
        const key = `${rootId}:${depth}`;
        groups.set(key, [...(groups.get(key) || []), node]);
      }

      const maxDepth = Math.max(1, ...nodes.map((node) => node.layoutDepth || 0));
      const singleRootStep = Math.max(92, Math.min(150, canvasSpan / (maxDepth + 1.7)));
      const multiRootStep = Math.max(72, Math.min(112, canvasSpan / (maxDepth + 2.6)));
      for (const [key, groupNodes] of groups) {
        const [rootId, depthValue] = key.split(':');
        const depth = Number(depthValue || 0);
        const rootCenter = rootCenters.get(rootId) || { x: width / 2, y: height / 2, angle: -Math.PI / 2 };
        const ordered = groupNodes.sort((left, right) => left.title.localeCompare(right.title, 'zh-CN'));
        for (const [index, node] of ordered.entries()) {
          if (depth === 0) {
            node.targetX = rootCenter.x;
            node.targetY = rootCenter.y;
            continue;
          }

          const count = ordered.length;
          const localSpread = uniqueRootIds.length === 1 ? Math.PI * 2 : Math.min(Math.PI * 0.92, (Math.PI * 2 / uniqueRootIds.length) * 0.78);
          const baseAngle = uniqueRootIds.length === 1 ? -Math.PI / 2 + depth * 0.42 : rootCenter.angle;
          const angle = count === 1 ? baseAngle : baseAngle - localSpread / 2 + (localSpread * (index + 0.5)) / count;
          const ring = (uniqueRootIds.length === 1 ? singleRootStep : multiRootStep) * depth;
          node.targetX = rootCenter.x + Math.cos(angle) * ring;
          node.targetY = rootCenter.y + Math.sin(angle) * ring;
        }
      }

      let transform: ZoomTransform = d3.zoomIdentity;
      const spread = Math.max(1, Math.min(1.8, Math.sqrt(topicCount / 22)));
      const simulation = d3.forceSimulation<GraphCanvasNode>(nodes)
        .force('link', d3.forceLink<GraphCanvasNode, GraphCanvasLink>(links).id((node) => node.id).distance((link) => (link.type === 'parent' ? 140 : link.type === 'both' ? 154 : 168) * spread).strength(0.26))
        .force('charge', d3.forceManyBody<GraphCanvasNode>().strength((node) => node.isRoot ? -620 : -400).distanceMin(52).distanceMax(Math.max(width, height) * 0.82))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('x', d3.forceX<GraphCanvasNode>((node) => node.targetX ?? width / 2).strength((node) => node.isRoot ? 0.22 : 0.12))
        .force('y', d3.forceY<GraphCanvasNode>((node) => node.targetY ?? height / 2).strength((node) => node.isRoot ? 0.22 : 0.12))
        .force('collide', d3.forceCollide<GraphCanvasNode>((node) => node.collisionRadius).strength(0.92).iterations(2))
        .alpha(0.9)
        .alphaDecay(0.018);

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

      const draw = () => {
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
          const linkColor = link.type === 'parent'
            ? 'rgba(244, 114, 182, 0.58)'
            : link.type === 'both'
              ? 'rgba(251, 191, 36, 0.68)'
              : 'rgba(125, 211, 252, 0.58)';
          ctx.beginPath();
          ctx.moveTo(startX, startY);
          ctx.lineTo(endX, endY);
          if (link.type === 'parent') {
            ctx.setLineDash([6, 6]);
            ctx.strokeStyle = linkColor;
            ctx.lineWidth = 1.25;
          } else if (link.type === 'both') {
            ctx.setLineDash([10, 4, 2, 4]);
            ctx.strokeStyle = linkColor;
            ctx.lineWidth = 1.7;
          } else {
            ctx.setLineDash([]);
            ctx.strokeStyle = linkColor;
            ctx.lineWidth = 1.5;
          }
          ctx.stroke();
          ctx.setLineDash([]);
          drawArrowHead(endX, endY, Math.atan2(dy, dx), linkColor, link.type === 'both' ? 9 : link.type === 'parent' ? 7 : 8);
        }
        ctx.setLineDash([]);

        for (const node of nodes) {
          const x = node.x || 0;
          const y = node.y || 0;
          const isSelected = node.id === selectedTopicIdRef.current;
          const haloRadius = node.radius + (node.isMistake ? 10 : 7);

          const halo = ctx.createRadialGradient(x, y, node.radius * 0.4, x, y, haloRadius);
          halo.addColorStop(0, node.isMistake ? 'rgba(244, 63, 94, 0.34)' : 'rgba(129, 140, 248, 0.34)');
          halo.addColorStop(1, 'rgba(15, 23, 42, 0)');
          ctx.fillStyle = halo;
          ctx.beginPath();
          ctx.arc(x, y, haloRadius, 0, Math.PI * 2);
          ctx.fill();

          ctx.beginPath();
          ctx.arc(x, y, node.radius, 0, Math.PI * 2);
          ctx.fillStyle = node.isRoot ? '#fce7f3' : node.isMistake ? '#ffe4e6' : '#eef2ff';
          ctx.fill();
          ctx.strokeStyle = isSelected ? '#fbbf24' : node.isMistake ? '#fb7185' : node.isRoot ? '#f472b6' : '#93c5fd';
          ctx.lineWidth = isSelected ? 3 : 1.8;
          ctx.stroke();

          ctx.fillStyle = node.isRoot ? '#be185d' : node.isMistake ? '#be123c' : '#1e3a8a';
          ctx.font = `800 ${node.isRoot ? 11 : 10}px Nunito, Segoe UI, sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(node.isRoot ? 'ROOT' : String(Math.max(1, node.topic.difficulty || 1)), x, y);

          const label = node.title.length > 18 ? `${node.title.slice(0, 18)}...` : node.title;
          ctx.font = '700 11px Nunito, Segoe UI, sans-serif';
          const labelWidth = Math.min(164, ctx.measureText(label).width + 20);
          const labelX = x - labelWidth / 2;
          const labelY = y + node.radius + 9;
          ctx.fillStyle = isSelected ? 'rgba(251, 191, 36, 0.92)' : 'rgba(15, 23, 42, 0.78)';
          drawPill(labelX, labelY, labelWidth, 22, 11);
          ctx.fill();
          ctx.fillStyle = isSelected ? '#111827' : '#f8fafc';
          ctx.fillText(label, x, labelY + 11);
        }

        ctx.restore();
      };

      simulation.on('tick', draw);
      redrawRef.current = draw;

      const selection = d3.select<HTMLCanvasElement, unknown>(canvas);
      selection.on('.zoom', null).on('.drag', null).on('click', null);

      const zoom = d3.zoom<HTMLCanvasElement, unknown>()
        .scaleExtent([0.45, 4.5])
        .on('zoom', (event) => {
          transform = event.transform;
          draw();
        });

      const pointerInGraph = (event: MouseEvent | TouchEvent) => transform.invert(d3.pointer(event, canvas));

      const drag = d3.drag<HTMLCanvasElement, unknown>()
        .container(canvas)
        .subject((event) => {
          const [x, y] = pointerInGraph(event.sourceEvent);
          return simulation.find(x, y, 28 / transform.k) || undefined;
        })
        .on('start', (event) => {
          const subject = event.subject as GraphCanvasNode | undefined;
          if (!subject) return;
          if (!event.active) simulation.alphaTarget(0.28).restart();
          subject.fx = subject.x;
          subject.fy = subject.y;
        })
        .on('drag', (event) => {
          const subject = event.subject as GraphCanvasNode | undefined;
          if (!subject) return;
          const [x, y] = pointerInGraph(event.sourceEvent);
          subject.fx = x;
          subject.fy = y;
          draw();
        })
        .on('end', (event) => {
          const subject = event.subject as GraphCanvasNode | undefined;
          if (!subject) return;
          if (!event.active) simulation.alphaTarget(0);
          subject.fx = null;
          subject.fy = null;
        });

      selection.call(zoom).call(drag);
      selection.on('click', (event) => {
        const [x, y] = pointerInGraph(event);
        const hit = simulation.find(x, y, 24 / transform.k);
        if (!hit) return;
        selectedTopicIdRef.current = hit.id;
        onSelectNodeRef.current(hit.topic);
        draw();
      });

      stopRender = () => {
        simulation.stop();
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
          name: '每日能量',
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
          name: '趋势曲线',
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
          { name: '提问积极性', max: 100 },
          { name: '专注度', max: 100 },
          { name: '思考响应性', max: 100 },
          { name: '逻辑理解力', max: 100 },
          { name: '知识掌握度', max: 100 },
        ],
      },
      series: [{
        name: 'AI 多维诊断',
        type: 'radar',
        data: [{
          value: radarValues,
          name: '当前画像',
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
            <h3 className="mt-1 text-lg font-black text-gray-800">近期积分获取趋势</h3>
          </div>
          <span className="rounded-full bg-pink-50 px-3 py-1 text-xs font-bold text-pink-600">周视图</span>
        </div>
        <div ref={trendRef} className="h-72 w-full" />
      </div>

      <div className="relative overflow-hidden rounded-[28px] border border-indigo-100 bg-white/85 p-5 shadow-sm lg:col-span-2">
        <div className="absolute -left-10 -bottom-12 h-36 w-36 rounded-full bg-cyan-200/40 blur-3xl"></div>
        <div className="relative mb-2">
          <p className="text-xs font-black uppercase tracking-[0.18em] text-indigo-400">Learning Profile</p>
          <h3 className="mt-1 text-lg font-black text-gray-800">AI 多维学情诊断</h3>
        </div>
        <div ref={radarRef} className="h-72 w-full" />
      </div>
    </div>
  );
}

export default function AdminDashboard() {
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
    questionActiveness: '待获取',
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
  const [graphProposals, setGraphProposals] = useState<any[]>([]);
  const [reviewingProposalId, setReviewingProposalId] = useState('');
  const [engineLogs, setEngineLogs] = useState<string[]>([]);
  const [dataLoading, setDataLoading] = useState(false);
  // 知识图谱状态
  const [graphNodes, setGraphNodes] = useState<GraphTopic[]>([]);
  const [selectedNode, setSelectedNode] = useState<GraphTopic | null>(null);
  const [selectedGraphRootId, setSelectedGraphRootId] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);

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
        setGraphProposals((graphData.proposals || []).filter((proposal: any) => proposal.trigger === 'resource_ingest' && proposal.status === 'proposed'));
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
        let activenessLabel = '良好';
        if (userInputCount >= 10) activenessLabel = '极佳';
        else if (userInputCount >= 5) activenessLabel = '良好';
        else if (userInputCount >= 1) activenessLabel = '一般';
        else activenessLabel = '待观察';

        // ================= 🌟 最终修复：完整显示周一到周日七天，再也不会少任何一天 =================
        // 固定显示完整一周七天
        const weekDays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
        // 初始化所有七天，默认得分0，确保100%显示，不会丢失任何一天
        const dailyScores: Record<string, number> = {
          '周一': 0,
          '周二': 0,
          '周三': 0,
          '周四': 0,
          '周五': 0,
          '周六': 0,
          '周日': 0
        };

        // 🌟 100%正确的周几映射：JS里getDay() 0=周日，1=周一，2=周二，3=周三，4=周四，5=周五，6=周六
        events.forEach((event: any) => {
          if (event.kind === 'score_change') {
            const eventDate = new Date(event.ts);
            const eventDayNum = eventDate.getDay();
            // 把数字精准转成对应的周几名称
            let dayName = '';
            if (eventDayNum === 1) dayName = '周一';
            else if (eventDayNum === 2) dayName = '周二';
            else if (eventDayNum === 3) dayName = '周三';
            else if (eventDayNum === 4) dayName = '周四';
            else if (eventDayNum === 5) dayName = '周五';
            else if (eventDayNum === 6) dayName = '周六';
            else if (eventDayNum === 0) dayName = '周日'; // 周日完整启用

            // 统计所有七天的得分
            if (dayName && dailyScores.hasOwnProperty(dayName)) {
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
      void appDialog.alert("仅支持视频、音频、图片、PDF、Word、PPT、TXT等学习常用格式", { title: '文件格式不支持', intent: 'warning' });
      return false;
    }

    if (file.size > 500 * 1024 * 1024) {
      void appDialog.alert("文件大小不能超过 500MB", { title: '文件过大', intent: 'warning' });
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
        if (status === 'completed' || status === 'failed') {
          window.clearInterval(intervalId);
          void fetchAllData();
        }
      } catch (error) {
        console.error('轮询资源解析状态失败', error);
        window.clearInterval(intervalId);
      }
    }, 3000);
  };

  const uploadPendingFilesForSubject = async (topicId: string, tags: string[]) => {
    const subject = getSubjectTag(tags);
    const languageId = getSubjectLanguageId(tags);
    for (const file of pendingResourceFiles) {
      const res = await ResourceAPI.uploadResource({
        file,
        topicId,
        resourceName: stripFileExtension(file.name),
        category: 'learn',
        subject,
        languageId,
      });
      const resourceId = res.data?.resource?.resource_id;
      if (resourceId) pollResourceIngestion(resourceId);
    }
  };

  const handleSaveSubject = async () => {
    const normalizedName = subjectName.trim();
    if (!normalizedName) {
      await appDialog.alert('请输入学科名', { title: '缺少学科名', intent: 'warning' });
      return;
    }

    setModalSaving(true);
    try {
      let topicId = editingSubject?.topic_id || '';
      let tags = editingSubject?.tags || [];

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

      await uploadPendingFilesForSubject(topicId, tags);
      setSubjectModalOpen(false);
      resetSubjectModal();
      await fetchAllData();
    } catch (error) {
      console.error('保存学科失败', error);
      await appDialog.alert('保存失败，请检查后端服务', { title: '保存失败', intent: 'error' });
    } finally {
      setModalSaving(false);
    }
  };

  const handleDeleteSubject = async (topic: GraphTopic) => {
    if (!(await appDialog.confirm(`确定删除「${topic.title}」以及其下的知识节点和资源吗？`, { title: '删除学科', intent: 'danger', confirmText: '删除' }))) return;

    setDeletingSubjectId(topic.topic_id);
    try {
      await KnowledgeAPI.deleteSubject(topic.topic_id);
      if (editingSubject?.topic_id === topic.topic_id) closeSubjectModal();
      await fetchAllData();
    } catch (error) {
      console.error('删除学科失败', error);
      await appDialog.alert('删除失败，请检查后端服务', { title: '删除失败', intent: 'error' });
    } finally {
      setDeletingSubjectId('');
    }
  };

  const handleDeleteExistingResource = async (resource: TopicResource) => {
    if (!(await appDialog.confirm(`确定删除资源「${resource.resource_name}」吗？`, { title: '删除资源', intent: 'danger', confirmText: '删除' }))) return;

    setDeletingResourceId(resource.resource_id);
    try {
      await ResourceAPI.deleteResource(resource.resource_id);
      setExistingSubjectResources((prev) => prev.filter((item) => item.resource_id !== resource.resource_id));
      void fetchAllData();
    } catch (error) {
      console.error('删除资源失败', error);
      await appDialog.alert('删除资源失败，请检查后端服务', { title: '删除资源失败', intent: 'error' });
    } finally {
      setDeletingResourceId('');
    }
  };

  const subjectRoots = useMemo(
    () => graphNodes.filter((topic) => (topic.tags || []).includes('facet:root')),
    [graphNodes],
  );

  const countNodesUnderRoot = (rootId: string) => {
    const childIds = new Set<string>();

    const walk = (parentId: string) => {
      for (const topic of graphNodes) {
        if (!(topic.parent_ids || []).includes(parentId) && !(topic.prerequisite_ids || []).includes(parentId)) continue;
        if (childIds.has(topic.topic_id)) continue;
        childIds.add(topic.topic_id);
        walk(topic.topic_id);
      }
    };

    walk(rootId);
    return childIds.size;
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
      await appDialog.alert("请先选择要推送的知识节点！", { title: '请选择知识节点', intent: 'warning' });
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
        await appDialog.alert("任务已成功推送至魔法舱！", { title: '推送成功', intent: 'success' });
        fetchAllData();
      } else {
        await appDialog.alert("推送失败，请检查后端服务是否启动", { title: '推送失败', intent: 'error' });
      }
    } catch (error) {
      console.error(error);
      await appDialog.alert("无法连接后端服务", { title: '连接失败', intent: 'error' });
    } finally {
      setIsLoading(false);
    }
  };

  const handleApproveProposal = async (proposal: any) => {
    setReviewingProposalId(proposal.proposal_id);
    try {
      await KnowledgeAPI.approveProposal(proposal.proposal_id, {
        title: proposal.title,
        summary: proposal.summary,
        parent_node_ids: proposal.parent_node_ids,
        edge_type: proposal.edge_type,
        tags: ['parent-approved'],
        reason: '家长确认 AI 建议节点',
      });
      await appDialog.alert('已新增知识节点，并回挂相关资源片段', { title: '审核完成', intent: 'success' });
      await fetchAllData();
    } catch (error) {
      console.error(error);
      await appDialog.alert('审核失败，请检查后端服务', { title: '审核失败', intent: 'error' });
    } finally {
      setReviewingProposalId('');
    }
  };

  const handleRejectProposal = async (proposal: any) => {
    setReviewingProposalId(proposal.proposal_id);
    try {
      await KnowledgeAPI.rejectProposal(proposal.proposal_id, '家长拒绝该新增节点');
      await appDialog.alert('已拒绝该知识节点建议', { title: '已拒绝', intent: 'info' });
      await fetchAllData();
    } catch (error) {
      console.error(error);
      await appDialog.alert('拒绝失败，请检查后端服务', { title: '拒绝失败', intent: 'error' });
    } finally {
      setReviewingProposalId('');
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
            <span className="text-lg font-medium">返回大厅</span>
          </button>
          <h1 className="text-lg font-semibold">家长控制台</h1>
          <div className="w-8"></div>
        </div>
      </div>

      {/* 标签页导航 */}
      <div className="max-w-5xl mx-auto mb-6 bg-white/80 backdrop-blur rounded-2xl shadow-sm">
        <div className="flex border-b border-gray-100">
          <button
            onClick={() => setActiveTab('task')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'task' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            📁 任务配置
          </button>
          <button
            onClick={() => setActiveTab('report')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'report' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            📊 AI 学情报告
          </button>
          <button
            onClick={() => setActiveTab('mistake')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'mistake' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            📝 错题本与回放
          </button>
          <button
            onClick={() => setActiveTab('graph')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'graph' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            🕸️ 知识图谱
          </button>
          <button
            onClick={() => setActiveTab('debug')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'debug' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            ⚙️ 系统调试
          </button>
          <button
            onClick={() => setActiveTab('settings')}
            className={`px-6 py-3 text-sm font-medium cursor-pointer transition-all ${activeTab === 'settings' ? 'text-pink-600 border-b-2 border-pink-500' : 'text-gray-500 hover:text-gray-700'}`}
          >
            🔧 设置
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
                  <h2 className="text-xl font-black text-gray-800">学科资源配置</h2>
                  <p className="mt-1 text-xs text-gray-400">两列卡片管理学科；新建或编辑时上传学习资源，单文件最大 500MB。</p>
                </div>
                <span className="rounded-full border border-pink-100 bg-pink-50 px-3 py-1 text-xs font-semibold text-pink-600">
                  {subjectRoots.length} 个学科
                </span>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {subjectRoots.map((root) => {
                  const nodeCount = countNodesUnderRoot(root.topic_id);
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
                          <span className="rounded-full bg-white/80 px-2.5 py-1 text-[11px] font-bold text-pink-500 shadow-sm">已配置</span>
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

                      <div className="relative mt-8 grid grid-cols-2 gap-3 text-xs text-gray-500">
                        <div className="rounded-2xl border border-white/80 bg-white/70 p-3">
                          <p className="font-bold text-gray-700">{nodeCount}</p>
                          <p>知识节点</p>
                        </div>
                        <div className="rounded-2xl border border-white/80 bg-white/70 p-3">
                          <p className="font-bold text-gray-700">{getSubjectTag(root.tags || []) || 'custom'}</p>
                          <p>学科标识</p>
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
                      <p className="text-base font-black text-gray-800">新建学科</p>
                      <p className="mt-1 text-xs text-gray-400">添加名称并导入资源</p>
                    </div>
                  </div>
                </button>
              </div>
            </div>

            {allResources.length > 0 && (
              <div className="rounded-[24px] border border-gray-100 bg-white/70 p-5">
                <h2 className="text-sm font-black text-gray-700 mb-4">资源解析状态</h2>
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
                          {res.media_type && `${res.media_type} `}
                          {res.size_bytes && ` ${(res.size_bytes / 1024 / 1024).toFixed(2)} MB`}
                        </p>
                      </div>
                      <span className={[
                        'shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold',
                        isProcessing ? 'bg-amber-100 text-amber-700' :
                        isCompleted ? 'bg-green-100 text-green-700' :
                        isFailed ? 'bg-red-100 text-red-700' :
                        'bg-gray-100 text-gray-500'
                      ].join(' ')}>
                        {isProcessing ? '解析中' : isCompleted ? '已完成' : isFailed ? '失败' : '等待'}
                      </span>
                    </div>
                  )})}
                </div>
              </div>
            )}

            <div className="rounded-[24px] border border-gray-100 bg-white/70 p-5">
              <h2 className="text-lg font-semibold text-gray-700 mb-4">派发学习任务</h2>
              <div className="mb-3">
                <label className="text-sm text-gray-500 mb-1 block">知识节点</label>
                <select
                  value={selectedPushTopicId}
                  onChange={(e) => setSelectedPushTopicId(e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-pink-200"
                >
                  <option value="">请选择知识节点</option>
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
                {isLoading ? "推送中..." : "推送至魔法舱"}
              </button>
            </div>

            <div className="border-t border-gray-100 pt-6">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-lg font-semibold text-gray-700">AI 建议新增知识点</h2>
                  <p className="text-xs text-gray-400 mt-1">来自资源切片入库，确认后会加入知识图谱并回挂相关资源。</p>
                </div>
                <span className="text-xs px-3 py-1 rounded-full bg-blue-50 text-blue-600 border border-blue-100">
                  {graphProposals.length} 条待审核
                </span>
              </div>

              {graphProposals.length === 0 ? (
                <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 p-4 text-sm text-gray-400 text-center">
                  暂无待审核的知识节点建议。
                </div>
              ) : (
                <div className="space-y-3">
                  {graphProposals.slice(0, 5).map((proposal) => (
                    <div key={proposal.proposal_id} className="rounded-xl border border-blue-100 bg-white p-4 shadow-sm">
                      <div className="flex justify-between gap-4">
                        <div className="min-w-0">
                          <p className="text-sm font-bold text-gray-800">{proposal.title}</p>
                          <p className="text-xs text-gray-500 mt-1 line-clamp-2">{proposal.summary || proposal.reason}</p>
                          <p className="text-xs text-blue-500 mt-2">
                            父节点：{(proposal.parent_node_ids || []).join(', ') || '待系统补齐'} · 关系：{proposal.edge_type}
                          </p>
                        </div>
                        <div className="flex flex-col gap-2 shrink-0">
                          <button
                            onClick={() => handleApproveProposal(proposal)}
                            disabled={reviewingProposalId === proposal.proposal_id}
                            className="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-bold hover:bg-blue-700 disabled:opacity-50"
                          >
                            确认新增
                          </button>
                          <button
                            onClick={() => handleRejectProposal(proposal)}
                            disabled={reviewingProposalId === proposal.proposal_id}
                            className="px-3 py-1.5 rounded-lg bg-gray-100 text-gray-600 text-xs font-medium hover:bg-gray-200 disabled:opacity-50"
                          >
                            拒绝
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* 2. AI 学情报告（完整显示周一到周日七天） */}
        {activeTab === 'report' && (
          <div className="relative overflow-hidden rounded-[32px] border border-white/80 bg-white/80 p-6 shadow-sm backdrop-blur">
            <div className="pointer-events-none absolute -right-20 -top-24 h-56 w-56 rounded-full bg-pink-200/45 blur-3xl"></div>
            <div className="pointer-events-none absolute -left-24 bottom-8 h-56 w-56 rounded-full bg-sky-200/45 blur-3xl"></div>
            {dataLoading ? (
              <div className="relative text-center py-10 text-gray-500">加载真实学情数据中...</div>
            ) : (
              <div className="relative space-y-6">
                <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                  <div>
                    <p className="text-xs font-black uppercase tracking-[0.24em] text-pink-400">Learning Report</p>
                    <h2 className="mt-1 text-2xl font-black text-gray-900">AI 学情报告</h2>
                    <p className="mt-1 text-xs text-gray-500">基于真实事件流、积分变化和互动状态生成。</p>
                  </div>
                  <div className="rounded-full border border-pink-100 bg-white/80 px-4 py-2 text-xs font-bold text-pink-600 shadow-sm">
                    自动同步 · 周期视图
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  <div className="relative overflow-hidden rounded-[26px] border border-pink-100 bg-gradient-to-br from-white to-pink-50 p-5 shadow-sm">
                    <div className="absolute right-4 top-4 h-12 w-12 rounded-2xl bg-pink-100"></div>
                    <p className="text-sm font-bold text-gray-500">今日获智智慧星</p>
                    <div className="mt-3 flex items-end gap-2">
                      <p className="text-4xl font-black text-gray-900">{learningData.todayStar}</p>
                      {learningData.todayStarIncrease > 0 && (
                        <span className="mb-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-black text-emerald-600">+{learningData.todayStarIncrease}</span>
                      )}
                    </div>
                    <p className="mt-2 text-xs text-gray-400">累计积分与今日增量</p>
                  </div>

                  <div className="relative overflow-hidden rounded-[26px] border border-sky-100 bg-gradient-to-br from-white to-sky-50 p-5 shadow-sm">
                    <div className="absolute right-4 top-4 h-12 w-12 rounded-2xl bg-sky-100"></div>
                    <p className="text-sm font-bold text-gray-500">当前专注时长</p>
                    <div className="mt-3 flex items-end gap-2">
                      <p className="text-4xl font-black text-gray-900">{learningData.focusTime}</p>
                      <span className="mb-1 text-sm font-black text-sky-600">分钟</span>
                    </div>
                    <p className="mt-2 text-xs text-gray-400">{learningData.focusTime > 0 ? '今日学习中' : '等待今日学习事件'}</p>
                  </div>

                  <div className="relative overflow-hidden rounded-[26px] border border-indigo-100 bg-gradient-to-br from-white to-indigo-50 p-5 shadow-sm">
                    <div className="absolute right-4 top-4 h-12 w-12 rounded-2xl bg-indigo-100"></div>
                    <p className="text-sm font-bold text-gray-500">提问积极性</p>
                    <div className="mt-3 flex items-end gap-2">
                      <p className="text-4xl font-black text-gray-900">{learningData.questionActiveness}</p>
                      <span className="mb-1 text-xs font-black text-indigo-500">互动画像</span>
                    </div>
                    <p className="mt-2 text-xs text-gray-400">基于今日用户输入次数</p>
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
                <h2 className="text-xl font-bold text-gray-800">智能错题流</h2>
              </div>
              <p className="text-xs text-gray-500 mb-6 pb-4 border-b border-gray-100">
                系统依据 FSM 状态机自动抓取，拒绝无效刷题
              </p>
              
              <div className="flex-1 overflow-y-auto space-y-4 pr-2 scrollbar-hide">
                {dataLoading ? (
                  <div className="text-center py-6 text-gray-400 animate-pulse">正在从底层读取错题本...</div>
                ) : knowledgePoints.length === 0 ? (
                  <div className="text-center py-10 bg-gray-50 rounded-xl border border-dashed border-gray-200">
                    <span className="text-4xl block mb-2">🏆</span>
                    <p className="text-gray-500 font-medium">太棒了，暂无错题记录！</p>
                  </div>
                ) : (
                  knowledgePoints.map((kp) => (
                    <div key={kp.id} className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow relative overflow-hidden group">
                      <div className="absolute left-0 top-0 bottom-0 w-1.5 bg-gradient-to-b from-pink-300 to-pink-500"></div>
                      <div className="flex justify-between items-start mb-3">
                        <h3 className="font-bold text-gray-800 text-base">{kp.name}</h3>
                        <span className="bg-pink-50 text-pink-600 text-xs px-2 py-1 rounded-md font-medium flex items-center gap-1">
                          <AlertCircle size={12} /> 待攻克
                        </span>
                      </div>
                      
                      <div className="grid grid-cols-2 gap-2 mb-4">
                        <div className="flex items-center gap-2 text-xs text-gray-500 bg-gray-50 p-2 rounded-lg">
                          <Video size={14} className="text-blue-400" />
                          <span>相关视频: <strong className="text-gray-700">{kp.resourceCount}</strong></span>
                        </div>
                        <div className="flex items-center gap-2 text-xs text-gray-500 bg-gray-50 p-2 rounded-lg">
                          <Clock size={14} className="text-orange-400" />
                          <span className="truncate" title={kp.lastReview}>首错: {kp.lastReview.split(' ')[0]}</span>
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
                            await appDialog.alert("任务已推送到孩子的魔法舱！", { title: '推送成功', intent: 'success' });
                          } catch (e) {
                            await appDialog.alert("推送失败，请检查网络", { title: '推送失败', intent: 'error' });
                          }
                        }}
                        className="w-full py-2.5 bg-gray-900 text-white text-sm font-bold rounded-lg hover:bg-pink-500 transition-colors cursor-pointer"
                      >
                        ⚡ 立即派发重测任务
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
          <div className="h-[760px]">
            <div className="relative flex h-full flex-col overflow-hidden rounded-[2rem] border border-indigo-200/20 bg-slate-950 p-5 shadow-2xl shadow-indigo-950/20">
              <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_15%_12%,rgba(244,114,182,0.23),transparent_28%),radial-gradient(circle_at_84%_18%,rgba(56,189,248,0.18),transparent_28%),linear-gradient(135deg,rgba(15,23,42,0.94),rgba(49,46,129,0.88))]"></div>
              <div className="relative mb-4 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="flex items-start gap-3">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white/10 text-cyan-200 ring-1 ring-white/15">
                    <Network size={23} />
                  </div>
                  <div>
                    <h2 className="text-xl font-black text-white">知识图谱</h2>
                    <p className="mt-1 text-xs text-indigo-100/70">D3 力导向结构图，拖拽节点、滚轮缩放，点击查看掌握情况。</p>
                  </div>
                </div>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                  <label className="flex items-center gap-2 rounded-2xl border border-white/10 bg-white/10 px-3 py-2 text-xs font-bold text-white/80">
                    根节点
                    <select
                      value={selectedGraphRootId}
                      onChange={(e) => {
                        setSelectedGraphRootId(e.target.value);
                        setSelectedNode(null);
                        setIsModalOpen(false);
                      }}
                      className="min-w-40 rounded-xl border border-white/10 bg-slate-950/80 px-3 py-1.5 text-xs text-white outline-none focus:ring-2 focus:ring-cyan-300/40"
                    >
                      <option value="">全部图谱</option>
                      {subjectRoots.map((root) => (
                        <option key={root.topic_id} value={root.topic_id}>{root.title}</option>
                      ))}
                    </select>
                  </label>
                  <div className="flex shrink-0 gap-2 text-[11px] font-bold text-white/80">
                    <span className="rounded-full border border-white/10 bg-white/10 px-3 py-1">{visibleGraphNodes.length} 节点</span>
                    <span className="rounded-full border border-white/10 bg-white/10 px-3 py-1">{visibleGraphEdgeCount} 关系</span>
                  </div>
                </div>
              </div>

              {selectedGraphRoot && (
                <div className="relative mb-3 rounded-2xl border border-cyan-300/20 bg-cyan-400/10 px-4 py-2 text-xs font-semibold text-cyan-50">
                  当前只看「{selectedGraphRoot.title}」根节点下的子图。切回“全部图谱”可查看完整结构。
                </div>
              )}

              <div className="relative flex-1 overflow-hidden rounded-[28px] border border-white/10 bg-slate-900/70 shadow-inner">
                <div className="pointer-events-none absolute inset-0 opacity-25 [background-image:linear-gradient(rgba(255,255,255,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.08)_1px,transparent_1px)] [background-size:28px_28px]"></div>
                {visibleGraphNodes.length === 0 ? (
                  <div className="relative flex h-full flex-col items-center justify-center text-center text-indigo-100/70">
                    <Network size={44} className="mb-3 text-indigo-200/60" />
                    <p className="text-sm font-bold">知识图谱生成中...</p>
                    <p className="mt-1 text-xs">上传学科资源后会自动扩展节点关系。</p>
                  </div>
                ) : (
                  <KnowledgeGraphCanvas
                    topics={visibleGraphNodes}
                    selectedTopicId={selectedNode?.topic_id}
                    mistakeTopicIds={mistakeTopicIds}
                    onSelectNode={(node) => {
                      setSelectedNode(node);
                      setIsModalOpen(true);
                    }}
                  />
                )}

                <div className="pointer-events-none absolute bottom-4 left-4 flex flex-wrap gap-2 text-[11px] font-bold text-white/80">
                  <span className="rounded-full border border-pink-300/30 bg-pink-500/15 px-3 py-1">虚线：层级归属 parent_ids</span>
                  <span className="rounded-full border border-cyan-300/30 bg-cyan-500/15 px-3 py-1">实线：前置依赖 prerequisite_ids</span>
                  <span className="rounded-full border border-amber-300/30 bg-amber-500/15 px-3 py-1">黄线：层级 + 前置复合关系</span>
                  <span className="rounded-full border border-rose-300/30 bg-rose-500/15 px-3 py-1">粉色光晕：错题节点</span>
                </div>
              </div>
            </div>

            {isModalOpen && selectedNode && (
              <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                <div className="bg-white rounded-[28px] shadow-2xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in duration-200">
                  <div className="relative overflow-hidden bg-gradient-to-br from-slate-950 via-indigo-900 to-fuchsia-800 p-6 text-white">
                    <div className="absolute -right-10 -top-12 h-32 w-32 rounded-full bg-cyan-300/20 blur-2xl"></div>
                    <button 
                      onClick={() => setIsModalOpen(false)}
                      className="absolute top-4 right-4 text-white/70 hover:text-white cursor-pointer"
                    >
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
                    </button>
                    <div className="flex items-center gap-3">
                      <div className="bg-white/15 p-2 rounded-xl ring-1 ring-white/15">
                        <Info size={24} />
                      </div>
                      <div>
                        <p className="text-cyan-100 text-xs font-medium uppercase tracking-wider">Knowledge Node</p>
                        <h2 className="text-2xl font-bold">{selectedNode.title}</h2>
                      </div>
                    </div>
                  </div>
                  
                  <div className="p-6 space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div className="bg-gray-50 p-4 rounded-xl border border-gray-100 text-center">
                        <p className="text-xs text-gray-500 mb-1">绑定学习资源</p>
                        <p className="text-3xl font-black text-gray-800">{knowledgePoints.find(k => k.topicId === selectedNode.topic_id)?.resourceCount || 0}</p>
                      </div>
                      <div className="bg-pink-50 p-4 rounded-xl border border-pink-100 text-center">
                        <p className="text-xs text-pink-600 mb-1">累积错题数</p>
                        <p className="text-3xl font-black text-pink-600">{knowledgePoints.find(k => k.topicId === selectedNode.topic_id) ? '1' : '0'}</p>
                      </div>
                    </div>
                    
                    <div className="bg-blue-50/50 border border-blue-100 p-4 rounded-xl">
                      <h4 className="text-sm font-bold text-gray-700 mb-2 flex items-center gap-2">
                        <Clock size={16} className="text-blue-500" /> 近期动态
                      </h4>
                      <p className="text-sm text-gray-600">
                        {knowledgePoints.find(k => k.topicId === selectedNode.topic_id) 
                          ? `最后出错时间: ${knowledgePoints.find(k => k.topicId === selectedNode.topic_id)?.lastReview}`
                          : "目前掌握良好，暂无报错记录。"}
                      </p>
                    </div>
                  </div>
                  
                  <div className="p-4 bg-gray-50 border-t border-gray-100 text-right">
                    <button 
                      onClick={() => setIsModalOpen(false)}
                      className="px-6 py-2 bg-gray-200 text-gray-700 font-medium rounded-lg hover:bg-gray-300 transition-colors cursor-pointer"
                    >
                      关闭
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 5. 系统调试 */}
        {activeTab === 'debug' && (
          <div className="bg-white/80 backdrop-blur rounded-2xl p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-700 mb-4">引擎决策日志</h2>
            <p className="text-xs text-gray-400 mb-4">直接读取 logs/ 目录下的数据</p>
            {dataLoading ? (
              <div className="text-center py-6 text-gray-500">加载日志中...</div>
            ) : (
              <div className="bg-gray-900 rounded-lg p-4 font-mono text-xs text-green-400 mb-6 max-h-60 overflow-y-auto">
                {engineLogs.length === 0 ? (
                  <p>[INFO] 暂无日志数据，等待系统事件...</p>
                ) : (
                  engineLogs.map((log, i) => <p key={i}>{log}</p>)
                )}
              </div>
            )}
            <div className="bg-red-50 rounded-lg p-4 border border-red-200">
              <p className="text-sm text-red-600 font-medium mb-2">⚠️ 危险操作区</p>
              <p className="text-xs text-gray-500 mb-3">这里的操作将直接影响底层状态，无法撤销。</p>
              <button 
                onClick={async () => {
                  if(await appDialog.confirm("确定要清空本地上下文状态吗？此操作无法撤销！", { title: '清空本地上下文', intent: 'danger', confirmText: '清空' })) {
                    try {
                      await fetch(`${apiBaseUrl}/session/reset`, { method: "POST" });
                      await appDialog.alert("已清空本地上下文状态", { title: '已清空', intent: 'success' });
                      fetchAllData();
                    } catch (e) {
                      await appDialog.alert("操作失败", { title: '操作失败', intent: 'error' });
                    }
                  }
                }}
                className="bg-white text-gray-700 border border-gray-200 px-3 py-1 rounded text-xs hover:bg-gray-100 cursor-pointer"
              >
                清空本地上下文状态
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
                    {subjectModalMode === 'create' ? '新建学科' : '编辑学科'}
                  </h2>
                  <p className="mt-1 text-sm text-white/80">填写学科名，并把课件、文档、音视频资料放入下方列表。</p>
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
                <label className="mb-2 block text-sm font-bold text-gray-700">学科名</label>
                <input
                  type="text"
                  value={subjectName}
                  onChange={(e) => setSubjectName(e.target.value)}
                  placeholder="例如：数学、英语阅读、物理实验"
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
                    <h3 className="text-sm font-black text-gray-800">资源列表</h3>
                    <p className="text-xs text-gray-400">拖入文件直接导入，也可以使用右侧加号选择。</p>
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
                        正在读取已有资源...
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
                          <p className="text-xs text-amber-700/70">待上传 · {(file.size / 1024 / 1024).toFixed(2)} MB</p>
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
                      <p className="mt-3 text-sm font-semibold text-gray-500">还没有资源</p>
                      <p className="mt-1 text-xs text-gray-400">拖入文件，或点击右上角加号导入。</p>
                    </div>
                  )}
                </div>

                {modalDragging && (
                  <div className="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-[20px] border-2 border-dashed border-pink-300 bg-white/80 text-pink-600 shadow-2xl backdrop-blur-md">
                    <UploadCloud size={58} strokeWidth={1.8} />
                    <p className="mt-3 text-lg font-black">松开导入资源</p>
                    <p className="mt-1 text-xs text-pink-400">支持视频、音频、图片、PDF、Word、PPT、TXT</p>
                  </div>
                )}
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-gray-100 bg-gray-50 px-6 py-4">
              <p className="text-xs text-gray-400">
                {pendingResourceFiles.length > 0 ? `${pendingResourceFiles.length} 个资源等待上传` : '保存后会刷新学科卡片'}
              </p>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={closeSubjectModal}
                  disabled={modalSaving}
                  className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-600 transition-colors hover:bg-gray-100 disabled:opacity-50"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={() => void handleSaveSubject()}
                  disabled={modalSaving || !subjectName.trim()}
                  className="rounded-xl bg-gray-900 px-5 py-2 text-sm font-bold text-white shadow-lg shadow-gray-200 transition-colors hover:bg-pink-600 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {modalSaving ? '保存中...' : subjectModalMode === 'create' ? '创建并导入' : '保存修改'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
