import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineStyle,
  type UTCTimestamp,
} from 'lightweight-charts';

import type {
  ExecutionMarker,
  KlineBar,
  StructureMarker,
  TradePlanOverlayLine,
} from '../../types/api';

interface KlineChartProps {
  bars: KlineBar[];
  overlayLines: TradePlanOverlayLine[];
  structures: StructureMarker[];
  executions: ExecutionMarker[];
}

const lineVisuals = {
  ENTRY: { color: '#2563eb', style: LineStyle.Solid },
  NO_CHASE: { color: '#f97316', style: LineStyle.Dashed },
  STOP: { color: '#ef4444', style: LineStyle.Solid },
  TARGET_1: { color: '#22c55e', style: LineStyle.Dashed },
  TARGET_2: { color: '#16a34a', style: LineStyle.Dashed },
  CURRENT: { color: '#737373', style: LineStyle.Dotted },
} as const;

function markerVisual(eventType: string) {
  if (eventType.startsWith('BOTTOM')) {
    return { position: 'belowBar' as const, shape: 'arrowUp' as const, color: '#16a34a' };
  }
  return { position: 'aboveBar' as const, shape: 'arrowDown' as const, color: '#dc2626' };
}

export function KlineChart({ bars, overlayLines, structures, executions }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || bars.length === 0) return undefined;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#525252',
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
        fontSize: 12,
      },
      grid: {
        vertLines: { color: '#f0f0f0' },
        horzLines: { color: '#f0f0f0' },
      },
      rightPriceScale: {
        borderColor: '#e5e5e5',
        scaleMargins: { top: 0.08, bottom: 0.28 },
      },
      timeScale: {
        borderColor: '#e5e5e5',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        vertLine: { color: '#a3a3a3', labelBackgroundColor: '#262626' },
        horzLine: { color: '#a3a3a3', labelBackgroundColor: '#262626' },
      },
      localization: {
        locale: 'zh-CN',
      },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#16a34a',
      downColor: '#dc2626',
      wickUpColor: '#16a34a',
      wickDownColor: '#dc2626',
      borderVisible: false,
    });
    candles.setData(
      bars.map((bar) => ({
        time: bar.time as UTCTimestamp,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    );
    overlayLines.forEach((line) => {
      const visual = lineVisuals[line.type];
      candles.createPriceLine({
        price: line.price,
        title: line.label,
        color: visual.color,
        lineStyle: visual.style,
        lineWidth: line.type === 'STOP' ? 2 : 1,
        axisLabelVisible: true,
      });
    });
    const firstTime = bars[0].time;
    const lastTime = bars[bars.length - 1].time;
    const structureMarkers = structures
      .map((structure) => ({
        structure,
        time: Math.floor(new Date(structure.event_ts).getTime() / 1000),
      }))
      .filter(({ time }) => time >= firstTime && time <= lastTime)
      .map(({ structure, time }) => ({
        ...markerVisual(structure.event_type),
        time: time as UTCTimestamp,
        text: structure.display_name,
        id: String(structure.id),
      }));
    const executionMarkers = executions
      .filter((marker) => marker.time >= firstTime && marker.time <= lastTime)
      .map((marker) => ({
        position: marker.position,
        shape: marker.shape,
        color: marker.color,
        time: marker.time as UTCTimestamp,
        text: marker.text,
        id: marker.id,
      }));
    createSeriesMarkers(
      candles,
      [...structureMarkers, ...executionMarkers].sort(
        (left, right) => Number(left.time) - Number(right.time),
      ),
    );
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    volume.priceScale().applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
    });
    volume.setData(
      bars.map((bar) => ({
        time: bar.time as UTCTimestamp,
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(22, 163, 74, 0.35)' : 'rgba(220, 38, 38, 0.35)',
      })),
    );
    chart.timeScale().fitContent();

    return () => chart.remove();
  }, [bars, executions, overlayLines, structures]);

  return <div className="kline-chart" ref={containerRef} role="img" aria-label="K 线与成交量图" />;
}
