import { ListChecks } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { interviewSheetApi } from '../../../api/interviewSheet';
import { useI18n } from '../../../i18n/useI18n';
import { Button } from '../../ui/button';
import type { RealtimeInterviewLaunchContext } from './realtimeInterviewHelpers';

interface RealtimeInterviewButtonProps {
  projectId: string;
  candidateId: string;
  matchingId?: string | null;
  interviewSheetId?: string | null;
  source?: RealtimeInterviewLaunchContext['source'];
  projectName?: string | null;
  candidateName?: string | null;
  candidateEmail?: string | null;
  candidateCvText?: string | null;
  variant?: 'default' | 'outline' | 'ghost';
  size?: 'default' | 'sm' | 'lg' | 'icon';
  className?: string;
  label?: string;
}

export function RealtimeInterviewButton({
  projectId,
  candidateId,
  matchingId,
  interviewSheetId,
  variant = 'outline',
  size = 'sm',
  className = '',
  label,
}: RealtimeInterviewButtonProps) {
  const navigate = useNavigate();
  const { t } = useI18n();
  const [isOpening, setIsOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    setIsOpening(true);
    setError(null);
    try {
      const sheetId = interviewSheetId || (await interviewSheetApi.generateOrOpen({
        candidate_id: candidateId,
        job_id: projectId,
        matching_id: matchingId || 'manual',
        interviewer_id: 'default',
      })).interview_sheet_id;

      navigate(`/interviews/${sheetId}`);
    } catch (openError) {
      console.error('Unable to open the canonical interview sheet:', openError);
      setError(openError instanceof Error ? openError.message : t('realtime.canonicalSheet.error'));
    } finally {
      setIsOpening(false);
    }
  };

  return (
    <div className="min-w-0">
      <Button
        onClick={() => void handleClick()}
        variant={variant}
        size={size}
        className={`max-w-full ${className}`}
        disabled={isOpening}
      >
        <ListChecks className="mr-2 h-4 w-4 shrink-0" />
        <span className="min-w-0 truncate">
          {isOpening ? t('realtime.canonicalSheet.opening') : label || t('realtime.canonicalSheet.action')}
        </span>
      </Button>
      {error ? <p className="mt-1 max-w-xs text-xs text-destructive">{error}</p> : null}
    </div>
  );
}
