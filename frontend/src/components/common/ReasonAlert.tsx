import { Alert } from 'antd';

interface ReasonAlertProps {
  title: string;
  reason: string;
  type?: 'info' | 'warning' | 'error' | 'success';
}

export function ReasonAlert({ title, reason, type = 'warning' }: ReasonAlertProps) {
  return <Alert showIcon type={type} message={title} description={reason} />;
}
