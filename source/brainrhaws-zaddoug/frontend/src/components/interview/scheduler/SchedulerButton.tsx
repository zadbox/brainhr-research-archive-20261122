import { useEffect, useState } from 'react';
import { Calendar, CalendarCheck } from 'lucide-react';
import { Button } from '../../ui/button';
import { InterviewSchedulerModal } from './InterviewSchedulerModal';
import { interviewSheetApi } from '../../../api/interviewSheet';
import {
    interviewAppointmentsApi,
    type HumanInterviewOutcome,
    type InterviewAppointment,
    type InterviewAppointmentStatus,
    type InterviewMode,
    type ScheduleInterviewRequest,
} from '../../../api/interviewAppointments';
import { useI18n } from '../../../i18n/useI18n';

interface SchedulerButtonProps {
    candidateId: string;
    jobId: string;
    matchingId: string;
    candidateName: string;
    candidateEmail?: string | null;
    existingSheetId?: string;
    initialData?: {
        scheduled_at?: string | null;
        end_at?: string | null;
        location?: string | null;
        scheduler_notes?: string | null;
        interviewer?: string | null;
        appointment_id?: string | null;
    };
    onUpdate?: () => void;
    variant?: 'default' | 'outline' | 'ghost';
    size?: 'default' | 'sm' | 'icon';
    label?: string;
    /** Mode proposé par défaut dans la fenêtre (IA ou recruteur). */
    defaultMode?: InterviewMode;
}

const ACTIVE_APPOINTMENT_STATUSES = new Set<InterviewAppointmentStatus>([
    'scheduled',
    'waiting_candidate',
    'in_progress',
    'paused',
    'wrapping_up',
]);

export function SchedulerButton({
    candidateId,
    jobId,
    matchingId,
    candidateName,
    candidateEmail,
    existingSheetId,
    initialData,
    onUpdate,
    variant = 'outline',
    size = 'sm',
    label,
    defaultMode = 'ai',
}: SchedulerButtonProps) {
    const { t } = useI18n();
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [appointment, setAppointment] = useState<InterviewAppointment | null>(null);
    // Un entretien recruteur annulé n'a plus de date sur la fiche.
    const hasScheduledInterview = appointment
        ? ACTIVE_APPOINTMENT_STATUSES.has(appointment.status)
        : Boolean(initialData?.appointment_id && initialData?.scheduled_at);

    useEffect(() => {
        if (!isModalOpen || !initialData?.appointment_id) return;

        let active = true;
        interviewAppointmentsApi.get(initialData.appointment_id)
            .then((data) => {
                if (active) setAppointment(data);
            })
            .catch((error) => {
                console.error('[SchedulerButton] Unable to load appointment:', error);
            });

        return () => {
            active = false;
        };
    }, [isModalOpen, initialData?.appointment_id]);

    const ensureSheet = async () => {
        if (existingSheetId) return existingSheetId;

        const res = await interviewSheetApi.generateOrOpen({
            candidate_id: candidateId,
            job_id: jobId,
            matching_id: matchingId,
            interviewer_id: 'brainrh_ai_interviewer'
        });
        return res.interview_sheet_id;
    };

    const handleCreate = async (request: ScheduleInterviewRequest) => {
        const sheetId = await ensureSheet();
        const created = await interviewAppointmentsApi.scheduleFromSheet(sheetId, request);
        setAppointment(created.appointment);
        onUpdate?.();
        return created;
    };

    const handleRecordOutcome = async (outcome: HumanInterviewOutcome) => {
        const appointmentId = appointment?.id || initialData?.appointment_id;
        if (!appointmentId) throw new Error(t('scheduler.error.default'));

        const updated = await interviewAppointmentsApi.recordOutcome(appointmentId, outcome);
        setAppointment(updated);
        onUpdate?.();
        return updated;
    };

    const handleCancel = async () => {
        const appointmentId = appointment?.id || initialData?.appointment_id;
        if (!appointmentId) return null;

        const cancelled = await interviewAppointmentsApi.cancel(appointmentId, 'Cancelled from BrainRH scheduler');
        setAppointment(cancelled.appointment);
        onUpdate?.();
        return cancelled.appointment;
    };

    return (
        <>
            <Button
                variant={variant}
                size={size}
                onClick={() => setIsModalOpen(true)}
                className={hasScheduledInterview
                    ? 'border-[color:var(--brain-ops-success)] text-[var(--brain-ops-success)] hover:bg-[color-mix(in_srgb,var(--brain-ops-success)_10%,transparent)]'
                    : ''}
                title={hasScheduledInterview ? t('scheduler.button.scheduled') : t('scheduler.button.schedule')}
                aria-label={label || (hasScheduledInterview ? t('scheduler.button.scheduled') : t('scheduler.button.schedule'))}
            >
                {hasScheduledInterview ? <CalendarCheck className="h-4 w-4" /> : <Calendar className="h-4 w-4" />}
                {label ? <span>{label}</span> : null}
            </Button>

            <InterviewSchedulerModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                initialData={initialData}
                initialAppointment={appointment}
                defaultMode={defaultMode}
                onCreate={handleCreate}
                onCancel={handleCancel}
                onRecordOutcome={handleRecordOutcome}
                candidateName={candidateName}
                candidateEmail={candidateEmail}
            />
        </>
    );
}
