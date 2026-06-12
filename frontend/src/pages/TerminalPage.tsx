import { Alert, Button } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';

import {
  getOrders,
  getPositions,
  getTerminalSummary,
  getTradePlanDetail,
  getTradePlans,
} from '../api/terminal';
import { BottomTimeline } from '../components/layout/BottomTimeline';
import { TopStatusBar } from '../components/layout/TopStatusBar';
import { EmptyState } from '../components/common/EmptyState';
import { LoadingBlock } from '../components/common/LoadingBlock';
import { PriceFramework } from '../components/terminal/PriceFramework';
import { SymbolPlanList } from '../components/terminal/SymbolPlanList';
import { TradePlanDetailPanel } from '../components/terminal/TradePlanDetailPanel';
import { useTerminalStore } from '../store/terminalStore';

export function TerminalPage() {
  const selectedId = useTerminalStore((state) => state.selectedTradePlanId);
  const selectPlan = useTerminalStore((state) => state.selectPlan);
  const summaryQuery = useQuery({ queryKey: ['terminal-summary'], queryFn: getTerminalSummary });
  const plansQuery = useQuery({ queryKey: ['trade-plans'], queryFn: getTradePlans });
  useQuery({ queryKey: ['positions'], queryFn: getPositions });
  useQuery({ queryKey: ['orders'], queryFn: getOrders });
  const detailQuery = useQuery({
    queryKey: ['trade-plan-detail', selectedId],
    queryFn: () => getTradePlanDetail(selectedId!),
    enabled: selectedId !== null,
  });

  const plans = plansQuery.data?.data ?? [];
  useEffect(() => {
    if (selectedId === null && plans.length > 0) {
      selectPlan(plans[0].id, plans[0].symbol);
    }
  }, [plans, selectPlan, selectedId]);

  const retry = () => {
    void summaryQuery.refetch();
    void plansQuery.refetch();
    if (selectedId !== null) void detailQuery.refetch();
  };

  if (summaryQuery.isLoading || plansQuery.isLoading) {
    return <main className="terminal-loading"><LoadingBlock /></main>;
  }
  if (summaryQuery.isError || plansQuery.isError) {
    const error = summaryQuery.error ?? plansQuery.error;
    return (
      <main className="terminal-error">
        <Alert
          showIcon
          type="error"
          message="交易终端暂时无法读取数据"
          description={error instanceof Error ? error.message : '请稍后重试'}
          action={<Button icon={<ReloadOutlined />} onClick={retry}>重新加载</Button>}
        />
      </main>
    );
  }

  const summary = summaryQuery.data!;
  const detail = detailQuery.data?.data ?? null;
  return (
    <main className="terminal-shell">
      <TopStatusBar summary={summary.data} meta={summary.meta} />
      {summary.data.risk_stop_reason ? (
        <Alert
          banner
          showIcon
          type="warning"
          message="当前暂停新增仓位"
          description={summary.data.risk_stop_reason}
        />
      ) : null}
      <div className="terminal-grid">
        <nav className="left-rail" aria-label="重点监控计划">
          <div className="section-heading">
            <div>
              <h2>重点监控计划</h2>
              <p>S/A 级 · {plans.length} 项</p>
            </div>
            <Button
              aria-label="刷新交易计划"
              icon={<ReloadOutlined />}
              loading={plansQuery.isFetching}
              onClick={() => void plansQuery.refetch()}
              type="text"
            />
          </div>
          <SymbolPlanList
            plans={plans}
            selectedId={selectedId}
            onSelect={(plan) => selectPlan(plan.id, plan.symbol)}
          />
        </nav>
        <section className="center-workspace">
          {detailQuery.isLoading ? <LoadingBlock /> : null}
          {!detailQuery.isLoading && detail ? <PriceFramework plan={detail.trade_plan} /> : null}
          {!detailQuery.isLoading && !detail ? <EmptyState description="请选择一个交易计划" /> : null}
        </section>
        <section className="right-rail">
          {detailQuery.isLoading ? <LoadingBlock /> : null}
          {!detailQuery.isLoading && detail ? <TradePlanDetailPanel detail={detail} /> : null}
          {!detailQuery.isLoading && !detail ? <EmptyState description="暂无计划详情" /> : null}
        </section>
      </div>
      <BottomTimeline detail={detail} />
    </main>
  );
}
