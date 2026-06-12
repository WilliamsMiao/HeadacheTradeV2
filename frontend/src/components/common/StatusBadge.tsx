import { Tag } from 'antd';
import { statusVisual } from '../../theme/statusDictionary';

interface StatusBadgeProps {
  status: string;
  label: string;
}

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const visual = statusVisual(status);
  return (
    <Tag
      className="status-badge"
      style={{
        color: visual.color,
        backgroundColor: visual.background,
        borderColor: visual.color,
      }}
    >
      {label}
    </Tag>
  );
}
