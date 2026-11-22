import * as React from 'react';
import { Toast } from './toast';
import { useToastStore } from '../../stores/useToastStore';
import { useI18n } from '../../i18n/useI18n';

export const Toaster: React.FC = () => {
  const { toasts, removeToast } = useToastStore();
  const { t } = useI18n();

  return (
    <div className="pointer-events-none fixed inset-x-4 bottom-4 z-[70] flex max-w-[24rem] flex-col gap-2 sm:left-auto sm:right-4">
      {toasts.map((toast) => (
        <Toast key={toast.id} {...toast} closeLabel={t('common.close')} onClose={removeToast} />
      ))}
    </div>
  );
};
