import { apiGet } from './client';
import type {
  KlineBar,
  Position,
  SimOrder,
  StructureMarker,
  TerminalSummary,
  Timeframe,
  TimelineEvent,
  TradePlan,
  TradePlanDetail,
  TradePlanOverlay,
} from '../types/api';

export const getTerminalSummary = () => apiGet<TerminalSummary>('/api/terminal/summary');

export const getTradePlans = () =>
  apiGet<TradePlan[]>('/api/trade-plans?active_only=true&priority=S,A');

export const getTradePlanDetail = (id: number) =>
  apiGet<TradePlanDetail>(`/api/trade-plans/${id}`);

export const getPositions = (symbol = '') =>
  apiGet<Position[]>(symbol ? `/api/positions?symbol=${encodeURIComponent(symbol)}` : '/api/positions');

export const getOrders = (symbol = '') =>
  apiGet<SimOrder[]>(
    symbol ? `/api/sim-orders?symbol=${encodeURIComponent(symbol)}` : '/api/sim-orders',
  );

export const getKlines = (symbol: string, timeframe: Timeframe, limit = 300) =>
  apiGet<KlineBar[]>(
    `/api/kline?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&limit=${limit}`,
  );

export const getTradePlanOverlay = (symbol: string, planId: number) =>
  apiGet<TradePlanOverlay>(
    `/api/trade-plan-overlays?symbol=${encodeURIComponent(symbol)}&plan_id=${planId}`,
  );

export const getStructures = (symbol: string, timeframe: Timeframe) =>
  apiGet<StructureMarker[]>(
    `/api/structures?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&limit=100`,
  );

export const getTimeline = (symbol: string, limit = 100) =>
  apiGet<TimelineEvent[]>(
    `/api/timeline?symbol=${encodeURIComponent(symbol)}&limit=${limit}`,
  );
