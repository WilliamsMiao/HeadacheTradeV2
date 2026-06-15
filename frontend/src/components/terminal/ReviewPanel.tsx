import { Alert, Collapse, Statistic, Table, Tag } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { lazy, Suspense, useMemo } from 'react';

import {
  getDailyStats,
  getFirstValidTrades,
  getJournalSummary,
} from '../../api/terminal';
import { tradingColors } from '../../theme/tradingColors';
import { LoadingBlock } from '../common/LoadingBlock';

const StatsChart = lazy(async () => {
  const module = await import('../charts/StatsChart');
  return { default: module.StatsChart };
});

export function ReviewPanel() {
  const journalQuery = useQuery({
    queryKey: ['journal-summary'],
    queryFn: getJournalSummary,
    refetchInterval: 60_000,
  });
  const dailyQuery = useQuery({
    queryKey: ['daily-stats'],
    queryFn: getDailyStats,
    refetchInterval: 60_000,
  });
  const firstValidQuery = useQuery({
    queryKey: ['first-valid-trades'],
    queryFn: getFirstValidTrades,
    refetchInterval: 60_000,
  });
  const journal = journalQuery.data?.data;
  const daily = dailyQuery.data?.data;
  const curveOption = useMemo(() => ({
    animation: false,
    grid: { left: 42, right: 16, top: 24, bottom: 32 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: journal?.curve.map((point) => `${point.trade_number}`) ?? [],
      name: '交易序号',
    },
    yAxis: { type: 'value', name: '累计 R' },
    series: [{
      data: journal?.curve.map((point) => point.cumulative_r) ?? [],
      type: 'line',
      smooth: false,
      symbolSize: 6,
      lineStyle: { color: tradingColors.armed, width: 2 },
      itemStyle: { color: tradingColors.armed },
    }],
  }), [journal?.curve]);
  const rejectionOption = useMemo(() => ({
    animation: false,
    grid: { left: 120, right: 16, top: 16, bottom: 24 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: {
      type: 'category',
      data: daily?.rejection_reasons.slice(0, 8).map((item) => item.reason) ?? [],
    },
    series: [{
      data: daily?.rejection_reasons.slice(0, 8).map((item) => item.count) ?? [],
      type: 'bar',
      itemStyle: { color: tradingColors.noChase },
    }],
  }), [daily?.rejection_reasons]);
  const loading = journalQuery.isLoading || dailyQuery.isLoading || firstValidQuery.isLoading;
  const error = journalQuery.error || dailyQuery.error || firstValidQuery.error;

  return (
    <section className="review-panel">
      <div className="section-heading">
        <div>
          <h2>统计与复盘</h2>
          <p>只统计真实模拟持仓；未成交计划不会进入胜率和收益曲线</p>
        </div>
      </div>
      {loading ? <LoadingBlock /> : null}
      {error ? <Alert showIcon type="error" message="复盘统计暂时无法读取" /> : null}
      {!loading && !error && journal && daily ? (
        <Collapse
          bordered={false}
          items={[{
            key: 'review',
            label: `已结束交易 ${journal.closed_trades} 笔`,
            children: <>
              <div className="review-metrics">
                <Statistic title="胜率" value={journal.win_rate * 100} precision={1} suffix="%" />
                <Statistic title="平均结果" value={journal.average_r} precision={2} suffix="R" />
                <Statistic title="累计结果" value={journal.cumulative_r} precision={2} suffix="R" />
                <Statistic title="最大回撤" value={journal.max_drawdown_r} precision={2} suffix="R" />
              </div>
              <div className="review-charts">
                <div>
                  <h3>逐笔累计 R</h3>
                  <Suspense fallback={<LoadingBlock />}>
                    <StatsChart option={curveOption} label="逐笔累计 R 曲线" />
                  </Suspense>
                </div>
                <div>
                  <h3>规则阻塞原因</h3>
                  <Suspense fallback={<LoadingBlock />}>
                    <StatsChart option={rejectionOption} label="规则阻塞原因统计" />
                  </Suspense>
                </div>
              </div>
              <h3>错失机会后续表现</h3>
              <p className="review-note">以下变化仅用于复盘过滤效果，不代表实际交易收益。</p>
              <Table
                columns={[
                  { title: '标的', dataIndex: 'symbol' },
                  {
                    title: '原因',
                    dataIndex: 'status_display_name',
                    render: (value: string) => <Tag>{value}</Tag>,
                  },
                  { title: '参考价', dataIndex: 'reference_price' },
                  { title: '当前价', dataIndex: 'current_price' },
                  {
                    title: '后续变化',
                    dataIndex: 'follow_up_pct',
                    render: (value: number | null) => value === null ? '数据不足' : `${value.toFixed(2)}%`,
                  },
                ]}
                dataSource={daily.missed_opportunities}
                locale={{ emptyText: '暂无可复盘的错失机会' }}
                pagination={false}
                rowKey="plan_id"
                scroll={{ x: 560 }}
                size="small"
              />
              <h3>每日首笔有效交易</h3>
              <Table
                columns={[
                  { title: '日期', dataIndex: 'date' },
                  { title: '标的', dataIndex: 'symbol' },
                  {
                    title: '结果',
                    dataIndex: 'result_r',
                    render: (value: number) => `${value.toFixed(2)}R`,
                  },
                ]}
                dataSource={firstValidQuery.data?.data ?? []}
                locale={{ emptyText: '暂无已建立的模拟持仓' }}
                pagination={false}
                rowKey="date"
                scroll={{ x: 420 }}
                size="small"
              />
            </>,
          }]}
        />
      ) : null}
    </section>
  );
}
