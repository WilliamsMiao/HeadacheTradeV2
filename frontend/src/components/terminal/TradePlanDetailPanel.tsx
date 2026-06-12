import { Collapse, Descriptions } from 'antd';
import type { TradePlanDetail } from '../../types/api';
import { DiagnosticChecklist } from '../common/DiagnosticChecklist';
import { ReasonAlert } from '../common/ReasonAlert';
import { StatusBadge } from '../common/StatusBadge';

interface TradePlanDetailPanelProps {
  detail: TradePlanDetail;
}

const money = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

export function TradePlanDetailPanel({ detail }: TradePlanDetailPanelProps) {
  const plan = detail.trade_plan;
  return (
    <aside className="detail-panel">
      <div className="detail-panel__heading">
        <div>
          <span>{plan.priority_level} 级计划</span>
          <h2>{plan.symbol.replace('US.', '')}</h2>
        </div>
        <StatusBadge status={plan.status} label={plan.display_status.display_name} />
      </div>
      <ReasonAlert
        title={plan.primary_blocker ? '当前主要阻塞' : '系统下一步'}
        reason={plan.primary_blocker || plan.next_system_action}
        type={plan.primary_blocker ? 'warning' : 'info'}
      />
      <section className="detail-section">
        <h3>实时状态</h3>
        <Descriptions column={1} size="small">
          <Descriptions.Item label="价格条件">{plan.price_gate_status}</Descriptions.Item>
          <Descriptions.Item label="实时确认">{plan.validation_status}</Descriptions.Item>
          <Descriptions.Item label="规则审批">{plan.rules_approval_display_name}</Descriptions.Item>
          <Descriptions.Item label="资金状态">{plan.capital_display_name}</Descriptions.Item>
        </Descriptions>
      </section>
      <section className="detail-section">
        <h3>资金快照</h3>
        <Descriptions column={1} size="small">
          <Descriptions.Item label="可用资金">
            {detail.capital_checks.available_cash_snapshot == null
              ? '尚未同步'
              : money.format(detail.capital_checks.available_cash_snapshot)}
          </Descriptions.Item>
          <Descriptions.Item label="单笔仓位上限">
            {detail.capital_checks.max_new_position_value == null
              ? '尚未计算'
              : money.format(detail.capital_checks.max_new_position_value)}
          </Descriptions.Item>
        </Descriptions>
      </section>
      <Collapse
        className="detail-collapse"
        ghost
        items={[
          {
            key: 'checks',
            label: `入场检查（${plan.checks.filter((check) => check.passed === true).length}/${plan.checks.length}）`,
            children: <DiagnosticChecklist checks={plan.checks} />,
          },
          {
            key: 'rules',
            label: '计划规则',
            children: (
              <div className="rule-copy">
                <strong>移动止盈</strong><p>{plan.trailing_rule}</p>
                <strong>时间止损</strong><p>{plan.time_stop_rule}</p>
                <strong>失效条件</strong><p>{plan.invalid_condition}</p>
              </div>
            ),
          },
        ]}
      />
    </aside>
  );
}
