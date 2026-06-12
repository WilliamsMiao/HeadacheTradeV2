import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('lightweight-charts', () => ({
  CandlestickSeries: 'CandlestickSeries',
  ColorType: { Solid: 'Solid' },
  HistogramSeries: 'HistogramSeries',
  createChart: () => ({
    addSeries: () => ({
      setData: () => undefined,
      priceScale: () => ({ applyOptions: () => undefined }),
    }),
    timeScale: () => ({ fitContent: () => undefined }),
    remove: () => undefined,
  }),
}));

import { KlineChart } from './KlineChart';

describe('KlineChart', () => {
  it('renders a stable chart surface when data is present', () => {
    render(
      <KlineChart
        bars={[
          { time: 1718208000, open: 100, high: 102, low: 99, close: 101, volume: 123456 },
        ]}
      />,
    );

    expect(screen.getByRole('img', { name: 'K 线与成交量图' })).toBeInTheDocument();
  });
});
