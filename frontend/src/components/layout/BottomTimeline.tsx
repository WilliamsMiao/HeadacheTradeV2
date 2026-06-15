import { ReloadOutlined } from '@ant-design/icons';
import { Button, Collapse, Tag } from 'antd';
import { useQuery } from '@tanstack/react-query';

import { getTimeline } from '../../api/terminal';
import { tradingColors } from '../../theme/tradingColors';

const eventTypeNames: Record<string, string> = {
  STRUCTURE: '结构事件',
  BATTLE_POOL: '结构作战池',
  TRADE_PLAN: '交易计划',
  SIM_ORDER: '模拟订单',
  POSITION: '模拟持仓',
};

function eventColor(severity: string) {
  if (severity === 'success') return tradingColors.filled;
  if (severity === 'warning') return tradingColors.noChase;
  if (severity === 'error' || severity === 'danger') return tradingColors.danger;
  return tradingColors.neutral;
}

export function BottomTimeline({ symbol }: { symbol: string | null }) {
  const query = useQuery({
    queryKey: ['timeline', symbol],
    queryFn: () => getTimeline(symbol!),
    enabled: symbol !== null,
    refetchInterval: 15_000,
  });
  const events = query.data?.data ?? [];
  return (
    <footer className="bottom-timeline">
      <div className="section-heading">
        <div>
          <h2>交易链路时间线</h2>
          <p>{symbol ? `${symbol} 从结构识别到持仓管理的完整记录` : '选择计划后显示完整交易链路'}</p>
        </div>
        <Button
          aria-label="刷新交易链路时间线"
          disabled={!symbol}
          icon={<ReloadOutlined />}
          loading={query.isFetching}
          onClick={() => void query.refetch()}
          type="text"
        />
      </div>
      <Collapse
        bordered={false}
        className="timeline-collapse"
        defaultActiveKey={['timeline']}
        items={[{
          key: 'timeline',
          label: `最近事件（${events.length}）`,
          children: <div className="timeline-strip">
        {events.length === 0 ? (
          <span className="timeline-empty">
            {symbol ? '当前标的暂无交易链路事件' : '请选择一个交易计划'}
          </span>
        ) : (
          events.slice(0, 20).map((event) => {
            return <div className="timeline-event" key={event.id}>
              <div className="timeline-event__meta">
                <time>{new Date(event.time).toLocaleString('zh-CN', { hour12: false })}</time>
                <Tag color={eventColor(event.severity)}>
                  {eventTypeNames[event.type] ?? '系统审计'}
                </Tag>
              </div>
              <strong>{event.title || '系统动作'}</strong>
              <span>{event.description || '系统未记录补充说明'}</span>
            </div>
          })
        )}
          </div>,
        }]}
      />
    </footer>
  );
}
