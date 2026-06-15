import { create } from 'zustand';

import type { Timeframe } from '../types/api';

interface TerminalState {
  selectedSymbol: string | null;
  selectedTradePlanId: number | null;
  selectedTimeframe: Timeframe;
  selectPlan: (id: number, symbol: string) => void;
  setTimeframe: (timeframe: Timeframe) => void;
}

export const useTerminalStore = create<TerminalState>((set) => ({
  selectedSymbol: null,
  selectedTradePlanId: null,
  selectedTimeframe: '60m',
  selectPlan: (id, symbol) => set({ selectedTradePlanId: id, selectedSymbol: symbol }),
  setTimeframe: (selectedTimeframe) => set({ selectedTimeframe }),
}));
