import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  type UTCTimestamp,
} from 'lightweight-charts';

import type { KlineBar } from '../../types/api';

interface KlineChartProps {
  bars: KlineBar[];
}

export function KlineChart({ bars }: KlineChartProps) {
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
  }, [bars]);

  return <div className="kline-chart" ref={containerRef} role="img" aria-label="K 线与成交量图" />;
}
