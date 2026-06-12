import { Skeleton } from 'antd';

export function LoadingBlock() {
  return (
    <div className="loading-block" aria-label="正在加载">
      <Skeleton active paragraph={{ rows: 5 }} />
    </div>
  );
}
