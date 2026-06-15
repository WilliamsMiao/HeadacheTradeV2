import type { Timeframe } from '../types/api';

export const timeframeOptions: Array<{ label: string; value: Timeframe }> = [
  { label: '1 分钟', value: '1m' },
  { label: '5 分钟', value: '5m' },
  { label: '15 分钟', value: '15m' },
  { label: '60 分钟', value: '60m' },
  { label: '日线', value: '1d' },
];

const timeframeNames: Record<Timeframe, string> = {
  '1m': '1 分钟',
  '5m': '5 分钟',
  '15m': '15 分钟',
  '60m': '60 分钟',
  '1d': '日线',
};

const staleAfterMs: Record<Timeframe, number> = {
  '1m': 3 * 60_000,
  '5m': 12 * 60_000,
  '15m': 30 * 60_000,
  '60m': 90 * 60_000,
  '1d': 36 * 60 * 60_000,
};

export function timeframeName(timeframe: Timeframe) {
  return timeframeNames[timeframe];
}

export function timeframeContext(timeframe: Timeframe) {
  if (timeframe === '1d') return '日线趋势周期';
  if (timeframe === '60m') return '60 分钟结构周期';
  return `${timeframeNames[timeframe]}执行观察周期`;
}

export function freshnessFor(syncedAt: string | undefined, timeframe: Timeframe) {
  if (!syncedAt) return { stale: true, label: '尚无数据' };
  const timestamp = new Date(syncedAt).getTime();
  if (!Number.isFinite(timestamp)) return { stale: true, label: '更新时间异常' };
  const stale = Date.now() - timestamp > staleAfterMs[timeframe];
  return { stale, label: stale ? '数据可能已过期' : '数据新鲜' };
}
