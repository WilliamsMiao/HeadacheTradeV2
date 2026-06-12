import { Alert, Button, Segmented } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { lazy, Suspense } from 'react';

import { getKlines, getStructures, getTradePlanOverlay } from '../../api/terminal';
import { useTerminalStore } from '../../store/terminalStore';
import type { TradePlan } from '../../types/api';
import { EmptyState } from '../common/EmptyState';
import { LoadingBlock } from '../common/LoadingBlock';

const KlineChart = lazy(async () => {
  const module = await import('../charts/KlineChart');
  return { default: module.KlineChart };
});

interface MarketChartPanelProps {
  plan: TradePlan;
}

export function MarketChartPanel({ plan }: MarketChartPanelProps) {
  const timeframe = useTerminalStore((state) => state.selectedTimeframe);
  const setTimeframe = useTerminalStore((state) => state.setTimeframe);
  const query = useQuery({
    queryKey: ['kline', plan.symbol, timeframe],
    queryFn: () => getKlines(plan.symbol, timeframe, timeframe === '1d' ? 250 : 300),
  });
  const overlayQuery = useQuery({
    queryKey: ['trade-plan-overlay', plan.id],
    queryFn: () => getTradePlanOverlay(plan.symbol, plan.id),
  });
  const structuresQuery = useQuery({
    queryKey: ['structures', plan.symbol, timeframe],
    queryFn: () => getStructures(plan.symbol, timeframe),
    enabled: timeframe === '60m',
  });
  const bars = query.data?.data ?? [];
  const overlayLines = overlayQuery.data?.data.lines ?? [];
  const structures = timeframe === '60m' ? (structuresQuery.data?.data ?? []) : [];
  const syncedAt = query.data?.meta.synced_at;

  return (
    <section className="market-chart-panel">
      <div className="section-heading">
        <div>
          <h2>{plan.symbol.replace('US.', '')} 行情</h2>
          <p>
            {plan.structure_display_name} · {timeframe === '60m' ? '60 分钟结构周期' : '日线趋势周期'}
          </p>
        </div>
        <div className="chart-controls">
          <Segmented
            aria-label="选择时间周期"
            onChange={(value) => setTimeframe(value as '60m' | '1d')}
            options={[
              { label: '60 分钟', value: '60m' },
              { label: '日线', value: '1d' },
            ]}
            value={timeframe}
          />
          <Button
            aria-label="刷新 K 线"
            icon={<ReloadOutlined />}
            loading={query.isFetching}
            onClick={() => void query.refetch()}
            type="text"
          />
        </div>
      </div>
      <div className="chart-freshness">
        <span>数据周期：{timeframe === '60m' ? '60 分钟' : '日线'}</span>
        <span>
          最新 K 线：{syncedAt ? new Date(syncedAt).toLocaleString('zh-CN', { hour12: false }) : '尚无数据'}
        </span>
      </div>
      <div className="chart-surface">
        {query.isLoading ? <LoadingBlock /> : null}
        {query.isError ? (
          <Alert
            showIcon
            type="error"
            message="K 线读取失败"
            description={query.error instanceof Error ? query.error.message : '请稍后重试'}
            action={<Button onClick={() => void query.refetch()}>重新加载</Button>}
          />
        ) : null}
        {!query.isLoading && !query.isError && bars.length === 0 ? (
          <EmptyState description={`当前没有 ${timeframe === '60m' ? '60 分钟' : '日线'} K 线数据`} />
        ) : null}
        {!query.isLoading && !query.isError && bars.length > 0 ? (
          <Suspense fallback={<LoadingBlock />}>
            <KlineChart bars={bars} overlayLines={overlayLines} structures={structures} />
          </Suspense>
        ) : null}
      </div>
      <div className="chart-plan-summary">
        <div><span>当前价</span><strong>{plan.current_price?.toFixed(2) ?? '—'}</strong></div>
        <div><span>计划入场价</span><strong>{plan.entry_price?.toFixed(2) ?? '—'}</strong></div>
        <div><span>硬止损价</span><strong>{plan.stop_price.toFixed(2)}</strong></div>
        <div><span>第一目标价</span><strong>{plan.target_1.toFixed(2)}</strong></div>
      </div>
      {timeframe === '60m' ? (
        <section className="structure-strip" aria-label="图中结构事件">
          <div className="structure-strip__heading">
            <strong>图中结构事件</strong>
            <span>{structures.length} 项</span>
          </div>
          {structures.length === 0 ? (
            <p>当前可见周期内暂无结构事件。</p>
          ) : (
            <div className="structure-event-list">
              {structures.slice(-6).reverse().map((structure) => (
                <details className="structure-event" key={structure.id}>
                  <summary>
                    <span>{structure.display_name}</span>
                    <time>{new Date(structure.event_ts).toLocaleString('zh-CN', { hour12: false })}</time>
                  </summary>
                  <p>{structure.reason}</p>
                  <div>
                    <span>事件价 {structure.price.toFixed(2)}</span>
                    <span>{structure.linked_battle_item_id ? '已进入结构作战池' : '未进入结构作战池'}</span>
                    <span>{structure.linked_trade_plan_id ? '已生成交易计划' : '未生成交易计划'}</span>
                  </div>
                </details>
              ))}
            </div>
          )}
        </section>
      ) : null}
    </section>
  );
}
