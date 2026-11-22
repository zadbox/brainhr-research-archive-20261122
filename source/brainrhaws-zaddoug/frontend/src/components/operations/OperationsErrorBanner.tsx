import { AlertCircle } from 'lucide-react';
import type { APIError } from '../../api/types';
import { useI18n } from '../../i18n/useI18n';
import { Alert, AlertDescription, AlertTitle } from '../ui/alert';

export interface OperationsErrorBannerProps {
  error: APIError | Error | string;
  className?: string;
}

export function OperationsErrorBanner({ error, className }: OperationsErrorBannerProps) {
  const { t } = useI18n();
  let code = 'ERROR';
  let details: unknown = null;

  if (typeof error === 'string') {
    details = error;
  } else if ('code' in error && 'message' in error) {
    code = error.code;
    details = error.details === undefined || error.details === null
      ? error.message
      : { message: error.message, details: error.details };
  } else if (error instanceof Error) {
    details = error.message;
  }

  return (
    <Alert variant="destructive" className={className}>
      <AlertCircle className="size-4" />
      <AlertTitle>
        {code !== 'ERROR' ? <span className="mr-2 font-mono text-xs">[{code}]</span> : null}
        {t('common.error')}
      </AlertTitle>
      <AlertDescription>
        <p>{t('common.unexpectedError')}</p>
        {details !== null && details !== undefined ? (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs font-medium">
              {t('common.technicalDetails')}
            </summary>
            <pre className="mt-2 max-h-40 overflow-auto rounded bg-destructive/10 p-2 text-xs">
              {typeof details === 'string' ? details : JSON.stringify(details, null, 2)}
            </pre>
          </details>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
