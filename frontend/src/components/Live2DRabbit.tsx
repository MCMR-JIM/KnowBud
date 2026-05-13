import { useEffect, useRef, useState } from 'react';
import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display';

(window as any).PIXI = PIXI;

Live2DModel.registerTicker(PIXI.Ticker);

// hijiki — 开源免费 Q 版卡通角色，圆润短腿、大眼小嘴，目前免费 CDN 中最接近儿童可爱风格的 Live2D 模型
const MODEL_URL = 'https://cdn.jsdelivr.net/npm/live2d-widget-model-hijiki@1.0.5/assets/hijiki.model.json';

interface Props {
  isSpeaking?: boolean;
  className?: string;
  fallbackEmoji?: string;
}

export default function Live2DRabbit({ isSpeaking = false, className, fallbackEmoji = '🐰' }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const modelRef = useRef<Live2DModel | null>(null);
  const mouthTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [status, setStatus] = useState<'loading' | 'loaded' | 'error'>('loading');

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const { width: w, height: h } = container.getBoundingClientRect();
    if (w === 0 || h === 0) return;

    let disposed = false;

    const app = new PIXI.Application({
      width: w,
      height: h,
      backgroundAlpha: 0,
      antialias: true,
      resolution: window.devicePixelRatio || 1,
      autoDensity: true,
    });

    container.appendChild(app.view as HTMLCanvasElement);
    (app.view as HTMLCanvasElement).style.width = '100%';
    (app.view as HTMLCanvasElement).style.height = '100%';
    appRef.current = app;

    Live2DModel.from(MODEL_URL)
      .then(model => {
        if (disposed || !appRef.current) return;
        modelRef.current = model;

        const s = Math.min(w / model.width, h / model.height) * 0.82;
        model.scale.set(s);
        model.x = w / 2;
        model.y = h / 2 + h * 0.02;
        model.anchor.set(0.5, 0.5);

        app.stage.addChild(model);
        setStatus('loaded');

        model.on('hit', () => handleTap(model));
      })
      .catch(err => {
        if (disposed) return;
        console.warn('Live2D 加载失败，使用 emoji 回退:', err);
        setStatus('error');
      });

    const onResize = () => {
      if (!container || !appRef.current) return;
      const { width: nw, height: nh } = container.getBoundingClientRect();
      if (nw === 0 || nh === 0) return;
      appRef.current.renderer.resize(nw, nh);
      const m = modelRef.current;
      if (m) {
        const s = Math.min(nw / m.width, nh / m.height) * 0.82;
        m.scale.set(s);
        m.x = nw / 2;
        m.y = nh / 2 + nh * 0.02;
      }
    };

    const ro = new ResizeObserver(onResize);
    ro.observe(container);

    return () => {
      disposed = true;
      ro.disconnect();
      if (mouthTimerRef.current) clearInterval(mouthTimerRef.current);
      if (appRef.current) {
        appRef.current.destroy(true, { children: true, texture: true });
        appRef.current = null;
      }
    };
  }, []);

  // AI 说话时嘴巴同步开合
  useEffect(() => {
    if (!modelRef.current || status !== 'loaded') return;

    if (isSpeaking) {
      let v = 0;
      let opening = true;
      mouthTimerRef.current = setInterval(() => {
        if (!modelRef.current) return;
        const cm = modelRef.current.internalModel.coreModel;
        if (!cm) return;
        v += opening ? 0.12 : -0.12;
        if (v >= 0.8) opening = false;
        if (v <= 0.1) opening = true;
        cm.setParamFloat('PARAM_MOUTH_OPEN_Y', v);
      }, 50);
    } else {
      if (mouthTimerRef.current) {
        clearInterval(mouthTimerRef.current);
        mouthTimerRef.current = null;
      }
      const cm = modelRef.current.internalModel.coreModel;
      if (cm) cm.setParamFloat('PARAM_MOUTH_OPEN_Y', 0);
    }

    return () => {
      if (mouthTimerRef.current) {
        clearInterval(mouthTimerRef.current);
        mouthTimerRef.current = null;
      }
    };
  }, [isSpeaking, status]);

  // 点击兔子 → 眨眼 + 摇头动画
  function handleTap(model: Live2DModel) {
    // 优先使用模型内置 tap 动作
    const defs = model.internalModel.motionManager?.definitions;
    if (defs) {
      const names = Object.keys(defs);
      const tapMotion = names.find(
        n => n.toLowerCase().includes('tap') || n.toLowerCase().includes('touch')
      );
      if (tapMotion) {
        model.motion(tapMotion);
        return;
      }
    }

    // 手动眨眼 + 摇头回退逻辑
    const cm = model.internalModel.coreModel;
    if (!cm) return;

    cm.setParamFloat('PARAM_EYE_L_OPEN', 0);
    cm.setParamFloat('PARAM_EYE_R_OPEN', 0);
    setTimeout(() => {
      cm.setParamFloat('PARAM_EYE_L_OPEN', 1);
      cm.setParamFloat('PARAM_EYE_R_OPEN', 1);
    }, 150);

    let count = 0;
    const shake = setInterval(() => {
      cm.setParamFloat('PARAM_ANGLE_Z', count % 2 === 0 ? 12 : -12);
      if (++count >= 4) {
        clearInterval(shake);
        cm.setParamFloat('PARAM_ANGLE_Z', 0);
      }
    }, 100);
  }

  return (
    <div ref={containerRef} className={className} style={{ width: '100%', height: '100%' }}>
      {status === 'error' && (
        <span
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 'clamp(2rem, 50%, 8rem)',
          }}
        >
          {fallbackEmoji}
        </span>
      )}
    </div>
  );
}
