import { describe, expect, it, vi } from 'vitest';

import { freshnessFor, timeframeContext, timeframeName } from './timeframes';

describe('terminal timeframes', () => {
  it('uses natural Chinese labels for every supported timeframe', () => {
    expect(timeframeName('1m')).toBe('1 分钟');
    expect(timeframeName('15m')).toBe('15 分钟');
    expect(timeframeContext('60m')).toBe('60 分钟结构周期');
    expect(timeframeContext('1d')).toBe('日线趋势周期');
  });

  it('reports stale and fresh timestamps using timeframe-specific thresholds', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-15T10:00:00Z'));
    expect(freshnessFor('2026-06-15T09:59:00Z', '1m').stale).toBe(false);
    expect(freshnessFor('2026-06-15T09:50:00Z', '1m').stale).toBe(true);
    expect(freshnessFor('2026-06-15T09:00:00Z', '60m').stale).toBe(false);
    expect(freshnessFor(undefined, '60m').label).toBe('尚无数据');
    vi.useRealTimers();
  });
});
