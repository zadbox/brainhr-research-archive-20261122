import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Bot, Calendar, CheckCircle2, Clock, ExternalLink, FileText, Mail, MapPin, UserRound, UserX, Video, XCircle } from 'lucide-react';
import {
    ChoiceTarget,
    OperationsDialog,
    OperationsDialogClose,
    OperationsDialogContent,
    OperationsDialogDescription,
    OperationsDialogFooter,
    OperationsDialogHeader,
    OperationsDialogTitle,
} from '../../operations';
import { Badge } from '../../ui/badge';
import { Button } from '../../ui/button';
import { Input } from '../../ui/input';
import { Label } from '../../ui/label';
import { Textarea } from '../../ui/textarea';
import { premiumFieldClass } from '../../shared/PremiumPage';
import { RecordingLinks } from '../recordings/RecordingLinks';
import { useToast } from '../../../hooks/useToast';
import { useI18n } from '../../../i18n/useI18n';
import { formatMessage } from '../../../i18n/formatMessage';
import type { TranslationKey } from '../../../i18n/messages';
import { useAuth } from '../../../features/auth/context/AuthContext';
import { cn } from '../../../lib/utils';
import {
    appointmentInvitation,
    type HumanInterviewOutcome,
    type HumanMeetingFormat,
    type InterviewAppointment,
    type InterviewAppointmentStatus,
    type InterviewInvitationState,
    type InterviewMode,
    type ScheduleInterviewRequest,
    type ScheduledInterviewResult,
} from '../../../api/interviewAppointments';

interface InterviewSchedulerModalProps {
    isOpen: boolean;
    onClose: () => void;
    initialData?: {
        scheduled_at?: string | null;
        end_at?: string | null;
        location?: string | null;
        scheduler_notes?: string | null;
        interviewer?: string | null;
        appointment_id?: string | null;
    };
    initialAppointment?: InterviewAppointment | null;
    /** Mode proposé à l'ouverture ; un entretien actif impose toujours le sien. */
    defaultMode?: InterviewMode;
    onCreate: (request: ScheduleInterviewRequest) => Promise<ScheduledInterviewResult>;
    onCancel?: () => Promise<InterviewAppointment | null>;
    onRecordOutcome?: (outcome: HumanInterviewOutcome) => Promise<InterviewAppointment>;
    candidateName: string;
    candidateEmail?: string | null;
}

const STATUS_LABEL_KEYS: Record<InterviewAppointmentStatus, TranslationKey> = {
    scheduled: 'scheduler.status.scheduled',
    waiting_candidate: 'scheduler.status.waiting',
    in_progress: 'scheduler.status.inProgress',
    paused: 'scheduler.status.paused',
    wrapping_up: 'scheduler.status.wrappingUp',
    completed: 'scheduler.status.completed',
    no_show: 'scheduler.status.noShow',
    cancelled: 'scheduler.status.cancelled',
    failed: 'scheduler.status.failed',
};

const FORMAT_LABEL_KEYS: Record<HumanMeetingFormat, TranslationKey> = {
    video: 'scheduler.format.video',
    phone: 'scheduler.format.phone',
    on_site: 'scheduler.format.on_site',
};

const INVITATION_LABEL_KEYS: Record<InterviewInvitationState['status'], TranslationKey> = {
    sent: 'scheduler.invitation.sent',
    not_requested: 'scheduler.invitation.not_requested',
    pending: 'scheduler.invitation.pending',
    not_configured: 'scheduler.invitation.not_configured',
    failed: 'scheduler.invitation.failed',
};

const ACTIVE_APPOINTMENT_STATUSES = new Set<InterviewAppointmentStatus>([
    'scheduled',
    'waiting_candidate',
    'in_progress',
    'paused',
    'wrapping_up',
]);
const DEFAULT_BOOKING_OFFSET_MINUTES = 15;
const EMAIL_PATTERN = /^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$/;
const choiceClass = cn(
    'flex w-full cursor-pointer items-start rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-3 transition-colors motion-reduce:transition-none',
    'hover:bg-[var(--brain-ops-surface-muted)] has-[:checked]:border-[color:var(--brain-ops-accent)] has-[:checked]:bg-[var(--brain-ops-accent-soft)]',
    'has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-[var(--brain-ops-focus-ring)]',
);
const labelClass = '[font-family:var(--brain-ops-font-command)]';

function toLocalDateTimeParts(value?: string | null) {
    if (!value) return { date: '', time: '' };
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return { date: '', time: '' };
    const offsetMs = d.getTimezoneOffset() * 60 * 1000;
    const localDate = new Date(d.getTime() - offsetMs);
    const isoStr = localDate.toISOString();
    return { date: isoStr.slice(0, 10), time: isoStr.slice(11, 16) };
}

function getDefaultStartParts() {
    const fiveMinutesMs = 5 * 60 * 1000;
    const suggested = new Date(Date.now() + DEFAULT_BOOKING_OFFSET_MINUTES * 60 * 1000);
    const rounded = new Date(Math.ceil(suggested.getTime() / fiveMinutesMs) * fiveMinutesMs);
    return toLocalDateTimeParts(rounded.toISOString());
}

function getBrowserTimeZone() {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'Africa/Casablanca';
}

function isBookableStart(value?: string | null) {
    if (!value) return false;
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return false;
    return d.getTime() > Date.now();
}

function isHttpsMeetingUrl(value: string) {
    if (!/^https:\/\/\S+$/i.test(value)) return false;
    try {
        const url = new URL(value);
        return url.protocol === 'https:' && Boolean(url.hostname) && !url.username && !url.password;
    } catch {
        return false;
    }
}

function normalizeErrorMessage(error: unknown, fallback: string): string {
    if (error && typeof error === 'object' && 'message' in error) {
        return String((error as { message?: unknown }).message || fallback);
    }
    if (error instanceof Error) return error.message;
    return fallback;
}

export function InterviewSchedulerModal({
    isOpen,
    onClose,
    initialData,
    initialAppointment,
    defaultMode = 'ai',
    onCreate,
    onCancel,
    onRecordOutcome,
    candidateName,
    candidateEmail
}: InterviewSchedulerModalProps) {
    const toast = useToast();
    const { language, t } = useI18n();
    const { user } = useAuth();
    const [loading, setLoading] = useState(false);
    const [cancelLoading, setCancelLoading] = useState(false);
    const [outcomeLoading, setOutcomeLoading] = useState(false);
    const [mode, setMode] = useState<InterviewMode>(defaultMode);
    const [date, setDate] = useState('');
    const [time, setTime] = useState('');
    const [email, setEmail] = useState('');
    const [durationMinutes, setDurationMinutes] = useState(45);
    const [notes, setNotes] = useState('');
    const [meetingFormat, setMeetingFormat] = useState<HumanMeetingFormat>('video');
    const [meetingUrl, setMeetingUrl] = useState('');
    const [meetingLocation, setMeetingLocation] = useState('');
    const [interviewerName, setInterviewerName] = useState('');
    const [interviewerEmail, setInterviewerEmail] = useState('');
    const [sendInvitation, setSendInvitation] = useState(true);
    const [invitationLanguage, setInvitationLanguage] = useState<'fr' | 'en'>('fr');
    const [appointment, setAppointment] = useState<InterviewAppointment | null>(initialAppointment ?? null);

    // Le formulaire se réinitialise à l'ouverture uniquement : un rendu du parent
    // (toast, rafraîchissement de la fiche) ne doit pas effacer la saisie en cours.
    const wasOpenRef = useRef(false);
    useEffect(() => {
        if (!isOpen) {
            wasOpenRef.current = false;
            return;
        }
        if (wasOpenRef.current) return;
        wasOpenRef.current = true;

        const scheduledAt = initialData?.scheduled_at;
        const parts = isBookableStart(scheduledAt)
            ? toLocalDateTimeParts(scheduledAt)
            : getDefaultStartParts();

        setDate(parts.date);
        setTime(parts.time);
        setEmail(candidateEmail || initialAppointment?.candidate_email || '');
        setDurationMinutes(45);
        setNotes(initialData?.scheduler_notes || '');
        setMode(defaultMode);
        setMeetingFormat('video');
        setMeetingUrl('');
        setMeetingLocation('');
        setInterviewerName(user?.display_name?.trim() || '');
        setInterviewerEmail(user?.email || '');
        setSendInvitation(true);
        setInvitationLanguage(language === 'en' ? 'en' : 'fr');
    }, [isOpen, initialData, initialAppointment, candidateEmail, defaultMode, user, language]);

    // Le rendez-vous peut arriver après l'ouverture : un entretien actif impose son mode.
    useEffect(() => {
        if (!isOpen) return;
        setAppointment(initialAppointment ?? null);
        if (initialAppointment && ACTIVE_APPOINTMENT_STATUSES.has(initialAppointment.status)) {
            setMode(initialAppointment.interview_mode ?? 'ai');
        }
    }, [isOpen, initialAppointment]);

    const hasActiveAppointment = appointment
        ? ACTIVE_APPOINTMENT_STATUSES.has(appointment.status)
        : Boolean(initialData?.appointment_id);
    const isHuman = mode === 'human';
    const appointmentIsHuman = appointment?.interview_mode === 'human';
    const canCancel = Boolean(onCancel && appointment && ACTIVE_APPOINTMENT_STATUSES.has(appointment.status));
    const busy = loading || cancelLoading || outcomeLoading;
    const createLabel = loading
        ? t('scheduler.create.creating')
        : hasActiveAppointment
            ? t('scheduler.create.alreadyScheduled')
            : appointment
                ? t('scheduler.create.newInterview')
                : t('scheduler.create.schedule');

    const validateHuman = (start: Date): string | null => {
        if (start.getTime() <= Date.now()) return t('scheduler.error.futureRequired');
        if (meetingFormat === 'video') {
            if (!meetingUrl.trim()) return t('scheduler.error.meetingUrlRequired');
            if (!isHttpsMeetingUrl(meetingUrl.trim())) return t('scheduler.error.meetingUrlInvalid');
        }
        if (meetingFormat === 'on_site' && !meetingLocation.trim()) return t('scheduler.error.addressRequired');
        if (sendInvitation && !EMAIL_PATTERN.test(email.trim())) return t('scheduler.error.invitationEmailRequired');
        if (interviewerEmail.trim() && !EMAIL_PATTERN.test(interviewerEmail.trim())) {
            return t('scheduler.error.interviewerEmailInvalid');
        }
        return null;
    };

    const handleCreate = async () => {
        try {
            setLoading(true);

            if (hasActiveAppointment) {
                toast.error(t('scheduler.error.activeExists'));
                return;
            }
            if (!date || !time) {
                toast.error(t('scheduler.error.dateTimeRequired'));
                return;
            }
            if (!isHuman && !email.trim()) {
                toast.error(t('scheduler.error.emailRequired'));
                return;
            }

            const localDate = new Date(`${date}T${time}`);
            if (Number.isNaN(localDate.getTime())) {
                toast.error(t('scheduler.error.invalidDateTime'));
                return;
            }

            if (isHuman) {
                const validationError = validateHuman(localDate);
                if (validationError) {
                    toast.error(validationError);
                    return;
                }
                const created = await onCreate({
                    mode: 'human',
                    input: {
                        start_at: localDate.toISOString(),
                        duration_minutes: durationMinutes,
                        candidate_name: candidateName,
                        candidate_email: email.trim() || null,
                        candidate_timezone: getBrowserTimeZone(),
                        interviewer_name: interviewerName.trim() || null,
                        interviewer_email: interviewerEmail.trim() || null,
                        meeting_format: meetingFormat,
                        meeting_url: meetingFormat === 'video' ? meetingUrl.trim() : null,
                        meeting_location: meetingFormat === 'video' ? null : meetingLocation.trim() || null,
                        scheduler_notes: notes || null,
                        send_invitation: sendInvitation,
                        invitation_language: invitationLanguage,
                    },
                });
                setAppointment(created.appointment);
                const invitation = appointmentInvitation(created.appointment);
                if (created.invitationWarning) {
                    toast.warning(t('scheduler.toast.invitationNotSentTitle'), t('scheduler.toast.invitationNotSentDetail'));
                } else if (invitation?.status === 'sent') {
                    toast.success(t('scheduler.toast.humanScheduledTitle'), t('scheduler.toast.humanInvitationSent'));
                } else {
                    toast.success(t('scheduler.toast.humanScheduledTitle'), t('scheduler.toast.humanNoInvitation'));
                }
                return;
            }

            const created = await onCreate({
                mode: 'ai',
                input: {
                    start_at: localDate.toISOString(),
                    duration_minutes: durationMinutes,
                    candidate_name: candidateName,
                    candidate_email: email.trim(),
                    candidate_timezone: getBrowserTimeZone(),
                    language_hint: 'fr',
                    scheduler_notes: notes || null,
                },
            });

            setAppointment(created.appointment);
            if (created.appointment.calcom_video_url) {
                toast.success(t('scheduler.toast.scheduledTitle'), t('scheduler.toast.scheduledDetail'));
            } else {
                toast.warning(t('scheduler.toast.fallbackTitle'), t('scheduler.toast.fallbackDetail'));
            }
        } catch (error: unknown) {
            toast.error(normalizeErrorMessage(error, t('scheduler.error.default')));
        } finally {
            setLoading(false);
        }
    };

    const handleCancel = async () => {
        if (!onCancel || !canCancel) return;
        try {
            setCancelLoading(true);
            const cancelled = await onCancel();
            if (cancelled) {
                setAppointment(cancelled);
                toast.success(t('scheduler.toast.cancelledTitle'), t('scheduler.toast.cancelledDetail'));
            }
        } catch (error: unknown) {
            toast.error(normalizeErrorMessage(error, t('scheduler.error.default')));
        } finally {
            setCancelLoading(false);
        }
    };

    const handleOutcome = async (outcome: HumanInterviewOutcome) => {
        if (!onRecordOutcome) return;
        try {
            setOutcomeLoading(true);
            const updated = await onRecordOutcome(outcome);
            setAppointment(updated);
            toast.success(t(outcome === 'completed' ? 'scheduler.toast.outcomeCompleted' : 'scheduler.toast.outcomeNoShow'));
        } catch (error: unknown) {
            toast.error(normalizeErrorMessage(error, t('scheduler.error.default')));
        } finally {
            setOutcomeLoading(false);
        }
    };

    const modeChoice = (value: InterviewMode, icon: ReactNode, title: string, hint: string) => (
        <ChoiceTarget className={choiceClass}>
            <input
                type="radio"
                name="interview-mode"
                value={value}
                checked={mode === value}
                onChange={() => setMode(value)}
                disabled={hasActiveAppointment || busy}
                className="sr-only"
            />
            <span className="mt-0.5 text-[var(--brain-ops-accent)]" aria-hidden="true">{icon}</span>
            <span className="min-w-0">
                <span className="block text-sm font-semibold text-[var(--brain-ops-text)]">{title}</span>
                <span className="mt-0.5 block text-xs leading-5 text-[var(--brain-ops-text-muted)]">{hint}</span>
            </span>
        </ChoiceTarget>
    );

    const humanInvitation = appointment ? appointmentInvitation(appointment) : null;
    const appointmentStarted = appointment ? Date.parse(appointment.start_at) <= Date.now() : false;
    const canRecordOutcome = Boolean(
        onRecordOutcome && appointment && appointmentIsHuman && ACTIVE_APPOINTMENT_STATUSES.has(appointment.status)
    );

    return (
        <OperationsDialog
            open={isOpen}
            onOpenChange={(open) => {
                if (!open) onClose();
            }}
        >
            <OperationsDialogContent className="max-h-[90vh] max-w-[640px] overflow-y-auto text-[var(--brain-ops-text)] [font-family:var(--brain-ops-font-body)]">
                <OperationsDialogClose aria-label={t('scheduler.close')} />
                <OperationsDialogHeader>
                    <OperationsDialogTitle className="pr-8 text-xl font-semibold tracking-[-0.01em]">
                        {t('scheduler.title')}
                    </OperationsDialogTitle>
                    <OperationsDialogDescription className="mt-2">
                        {candidateName}
                    </OperationsDialogDescription>
                </OperationsDialogHeader>

                <div className="space-y-6 py-4">
                    <fieldset className="space-y-2">
                        <legend className={`mb-2 text-sm font-medium ${labelClass}`}>{t('scheduler.mode.label')}</legend>
                        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                            {modeChoice('ai', <Bot className="h-4 w-4" />, t('scheduler.mode.ai'), t('scheduler.mode.aiHint'))}
                            {modeChoice('human', <UserRound className="h-4 w-4" />, t('scheduler.mode.human'), t('scheduler.mode.humanHint'))}
                        </div>
                    </fieldset>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <Label htmlFor="date" className={labelClass}>{t('scheduler.field.date')}</Label>
                            <div className="relative">
                                <Calendar className="absolute left-3 top-2.5 h-4 w-4 text-primary pointer-events-none" />
                                <Input
                                    id="date"
                                    type="date"
                                    value={date}
                                    onChange={(e) => setDate(e.target.value)}
                                    className={`${premiumFieldClass} pl-9`}
                                />
                            </div>
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="time" className={labelClass}>{t('scheduler.field.time')}</Label>
                            <div className="relative">
                                <Clock className="absolute left-3 top-2.5 h-4 w-4 text-primary pointer-events-none" />
                                <Input
                                    id="time"
                                    type="time"
                                    value={time}
                                    onChange={(e) => setTime(e.target.value)}
                                    className={`${premiumFieldClass} pl-9`}
                                />
                            </div>
                        </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-[1fr_140px] gap-4">
                        <div className="space-y-2">
                            <Label htmlFor="candidate-email" className={labelClass}>{t('scheduler.field.email')}</Label>
                            <div className="relative">
                                <Mail className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                                <Input
                                    id="candidate-email"
                                    type="email"
                                    placeholder={t('scheduler.field.emailPlaceholder')}
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    className={`${premiumFieldClass} pl-9`}
                                />
                            </div>
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="duration" className={labelClass}>{t('scheduler.field.duration')}</Label>
                            <Input
                                id="duration"
                                type="number"
                                min={5}
                                max={240}
                                step={5}
                                value={durationMinutes}
                                onChange={(e) => setDurationMinutes(Number(e.target.value || 45))}
                                className={premiumFieldClass}
                            />
                        </div>
                    </div>

                    {isHuman && (
                        <div className="space-y-4">
                            <fieldset>
                                <legend className={`mb-2 text-sm font-medium ${labelClass}`}>{t('scheduler.format.label')}</legend>
                                <div className="grid grid-cols-3 gap-2">
                                    {(['video', 'phone', 'on_site'] as const).map((format) => (
                                        <ChoiceTarget key={format} className={cn(choiceClass, 'items-center justify-center p-2 text-center text-sm font-medium')}>
                                            <input
                                                type="radio"
                                                name="meeting-format"
                                                value={format}
                                                checked={meetingFormat === format}
                                                onChange={() => setMeetingFormat(format)}
                                                disabled={hasActiveAppointment || busy}
                                                className="sr-only"
                                            />
                                            {t(FORMAT_LABEL_KEYS[format])}
                                        </ChoiceTarget>
                                    ))}
                                </div>
                            </fieldset>

                            {meetingFormat === 'video' ? (
                                <div className="space-y-2">
                                    <Label htmlFor="meeting-url" className={labelClass}>{t('scheduler.field.meetingUrl')}</Label>
                                    <div className="relative">
                                        <Video className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                                        <Input
                                            id="meeting-url"
                                            type="url"
                                            inputMode="url"
                                            placeholder={t('scheduler.field.meetingUrlPlaceholder')}
                                            value={meetingUrl}
                                            onChange={(e) => setMeetingUrl(e.target.value)}
                                            aria-describedby="meeting-url-hint"
                                            className={`${premiumFieldClass} pl-9`}
                                        />
                                    </div>
                                    <p id="meeting-url-hint" className="text-xs leading-5 text-[var(--brain-ops-text-muted)]">
                                        {t('scheduler.field.meetingUrlHint')}
                                    </p>
                                </div>
                            ) : (
                                <div className="space-y-2">
                                    <Label htmlFor="meeting-location" className={labelClass}>
                                        {meetingFormat === 'on_site' ? t('scheduler.field.address') : t('scheduler.field.phoneDetails')}
                                    </Label>
                                    <div className="relative">
                                        <MapPin className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                                        <Input
                                            id="meeting-location"
                                            placeholder={meetingFormat === 'on_site'
                                                ? t('scheduler.field.addressPlaceholder')
                                                : t('scheduler.field.phoneDetailsPlaceholder')}
                                            value={meetingLocation}
                                            onChange={(e) => setMeetingLocation(e.target.value)}
                                            maxLength={500}
                                            className={`${premiumFieldClass} pl-9`}
                                        />
                                    </div>
                                </div>
                            )}

                            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                                <div className="space-y-2">
                                    <Label htmlFor="interviewer-name" className={labelClass}>{t('scheduler.field.interviewerName')}</Label>
                                    <Input
                                        id="interviewer-name"
                                        placeholder={t('scheduler.field.interviewerNamePlaceholder')}
                                        value={interviewerName}
                                        onChange={(e) => setInterviewerName(e.target.value)}
                                        maxLength={200}
                                        className={premiumFieldClass}
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label htmlFor="interviewer-email" className={labelClass}>{t('scheduler.field.interviewerEmail')}</Label>
                                    <Input
                                        id="interviewer-email"
                                        type="email"
                                        value={interviewerEmail}
                                        onChange={(e) => setInterviewerEmail(e.target.value)}
                                        aria-describedby="interviewer-email-hint"
                                        className={premiumFieldClass}
                                    />
                                </div>
                                <p id="interviewer-email-hint" className="text-xs leading-5 text-[var(--brain-ops-text-muted)] sm:col-span-2">
                                    {t('scheduler.field.interviewerEmailHint')}
                                </p>
                            </div>

                            <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto] sm:items-start">
                                <ChoiceTarget className="items-start">
                                    <input
                                        type="checkbox"
                                        checked={sendInvitation}
                                        onChange={(e) => setSendInvitation(e.target.checked)}
                                        disabled={busy}
                                        aria-describedby="send-invitation-hint"
                                        className="mt-1"
                                    />
                                    <span className="min-w-0 text-sm">
                                        <span className="block font-medium">{t('scheduler.field.sendInvitation')}</span>
                                        <span id="send-invitation-hint" className="mt-0.5 block text-xs leading-5 text-[var(--brain-ops-text-muted)]">
                                            {t('scheduler.field.sendInvitationHint')}
                                        </span>
                                    </span>
                                </ChoiceTarget>
                                <select
                                    aria-label={t('scheduler.field.invitationLanguage')}
                                    value={invitationLanguage}
                                    onChange={(e) => setInvitationLanguage(e.target.value === 'en' ? 'en' : 'fr')}
                                    disabled={!sendInvitation || busy}
                                    className={cn(premiumFieldClass, 'h-10 rounded-md border px-3 text-sm')}
                                >
                                    <option value="fr">{t('language.french')}</option>
                                    <option value="en">{t('language.english')}</option>
                                </select>
                            </div>
                        </div>
                    )}

                    <div className="space-y-2">
                        <Label htmlFor="notes" className={labelClass}>
                            {isHuman ? t('scheduler.field.internalNotes') : t('scheduler.field.notes')}
                        </Label>
                        <Textarea
                            id="notes"
                            placeholder={isHuman ? t('scheduler.field.internalNotesPlaceholder') : t('scheduler.field.notesPlaceholder')}
                            value={notes}
                            onChange={(e) => setNotes(e.target.value)}
                            className={`${premiumFieldClass} min-h-[100px] resize-none`}
                        />
                    </div>

                    <div className="rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] p-4 text-sm text-[var(--brain-ops-text-muted)]">
                        <p className="flex items-start gap-2">
                            {isHuman ? <UserRound className="mt-0.5 h-4 w-4 text-primary" /> : <Bot className="mt-0.5 h-4 w-4 text-primary" />}
                            <span>
                                {isHuman
                                    ? formatMessage(t('scheduler.notice.human'), {
                                        interviewer: interviewerName.trim() || t('scheduler.notice.humanDefaultInterviewer'),
                                    })
                                    : t('scheduler.notice.aiRecording')}
                            </span>
                        </p>
                    </div>

                    {appointment && appointmentIsHuman && (
                        <section
                            aria-label={t('scheduler.human.title')}
                            className="space-y-3 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4"
                        >
                            <div className="flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2">
                                    <UserRound className="h-4 w-4 text-primary" />
                                    <p className="text-sm font-medium text-[var(--brain-ops-text)]">{t('scheduler.human.title')}</p>
                                </div>
                                <Badge variant="secondary">{t(STATUS_LABEL_KEYS[appointment.status])}</Badge>
                            </div>

                            <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
                                <div className="min-w-0">
                                    <dt className="text-[var(--brain-ops-text-muted)]">{t('scheduler.human.interviewer')}</dt>
                                    <dd className="truncate font-medium">{appointment.interviewer_name || '-'}</dd>
                                </div>
                                <div>
                                    <dt className="text-[var(--brain-ops-text-muted)]">{t('scheduler.human.format')}</dt>
                                    <dd className="font-medium">{appointment.meeting_format ? t(FORMAT_LABEL_KEYS[appointment.meeting_format]) : '-'}</dd>
                                </div>
                                {appointment.meeting_location && (
                                    <div className="min-w-0 sm:col-span-2">
                                        <dt className="text-[var(--brain-ops-text-muted)]">{t('scheduler.human.location')}</dt>
                                        <dd className="break-words font-medium">{appointment.meeting_location}</dd>
                                    </div>
                                )}
                                <div>
                                    <dt className="text-[var(--brain-ops-text-muted)]">{t('scheduler.human.invitation')}</dt>
                                    <dd className="font-medium">
                                        {humanInvitation ? t(INVITATION_LABEL_KEYS[humanInvitation.status] ?? 'scheduler.invitation.not_requested') : '-'}
                                    </dd>
                                </div>
                            </dl>

                            {appointment.meeting_url && isHttpsMeetingUrl(appointment.meeting_url) && (
                                <a
                                    href={appointment.meeting_url}
                                    target="_blank"
                                    rel="noreferrer noopener"
                                    className="inline-flex items-center gap-2 text-sm text-primary hover:underline"
                                >
                                    <ExternalLink className="h-4 w-4" />
                                    {t('scheduler.human.openLink')}
                                </a>
                            )}

                            {canRecordOutcome && (
                                <div className="space-y-2 border-t border-[color:var(--brain-ops-border)] pt-3">
                                    <p className={`text-sm font-medium ${labelClass}`}>{t('scheduler.outcome.label')}</p>
                                    <div className="flex flex-wrap gap-2">
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            onClick={() => handleOutcome('completed')}
                                            disabled={!appointmentStarted || busy}
                                        >
                                            <CheckCircle2 className="mr-2 h-4 w-4" />
                                            {outcomeLoading ? t('scheduler.outcome.saving') : t('scheduler.outcome.completed')}
                                        </Button>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            onClick={() => handleOutcome('no_show')}
                                            disabled={!appointmentStarted || busy}
                                        >
                                            <UserX className="mr-2 h-4 w-4" />
                                            {t('scheduler.outcome.noShow')}
                                        </Button>
                                    </div>
                                    {!appointmentStarted && (
                                        <p className="text-xs leading-5 text-[var(--brain-ops-text-muted)]">{t('scheduler.outcome.notStarted')}</p>
                                    )}
                                </div>
                            )}
                        </section>
                    )}

                    {appointment && !appointmentIsHuman && (
                        <div className="space-y-3 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4">
                            <div className="flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2">
                                    <Video className="h-4 w-4 text-primary" />
                                    <p className="text-sm font-medium text-[var(--brain-ops-text)]">{t('scheduler.calVideo')}</p>
                                </div>
                                <Badge variant={appointment.status === 'failed' ? 'destructive' : 'secondary'}>
                                    {t(STATUS_LABEL_KEYS[appointment.status])}
                                </Badge>
                            </div>

                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                                <div>
                                    <p className="text-[var(--brain-ops-text-muted)]">{t('scheduler.meta.booking')}</p>
                                    <p className="font-medium truncate">{appointment.calcom_booking_uid || '-'}</p>
                                </div>
                                <div>
                                    <p className="text-[var(--brain-ops-text-muted)]">{t('scheduler.meta.aiSession')}</p>
                                    <p className="font-medium truncate">{appointment.realtime_interview_id || '-'}</p>
                                </div>
                                <div>
                                    <p className="text-[var(--brain-ops-text-muted)]">{t('scheduler.meta.recording')}</p>
                                    <p className="font-medium">{appointment.recordings.length}</p>
                                </div>
                                <div>
                                    <p className="text-[var(--brain-ops-text-muted)]">{t('scheduler.meta.transcript')}</p>
                                    <p className="font-medium">{appointment.transcripts.length}</p>
                                </div>
                            </div>

                            <RecordingLinks
                                recordings={appointment.recordings}
                                title={t('scheduler.recordings')}
                                maxItems={2}
                                compact
                            />

                            {appointment.calcom_video_url && (
                                <a
                                    href={appointment.calcom_video_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="inline-flex items-center gap-2 text-sm text-primary hover:underline"
                                >
                                    <FileText className="h-4 w-4" />
                                    {t('scheduler.openVideo')}
                                </a>
                            )}

                            {appointment.last_error && (
                                <p className="text-sm text-destructive">{appointment.last_error}</p>
                            )}
                        </div>
                    )}
                </div>

                <OperationsDialogFooter>
                    {canCancel && (
                        <Button
                            type="button"
                            variant="outline"
                            onClick={handleCancel}
                            disabled={busy}
                            className="w-full sm:w-auto"
                        >
                            <XCircle className="mr-2 h-4 w-4" />
                            {cancelLoading ? t('scheduler.cancel.cancelling') : t('scheduler.cancel.action')}
                        </Button>
                    )}
                    <Button
                        type="button"
                        onClick={handleCreate}
                        disabled={busy || hasActiveAppointment}
                        className="w-full sm:w-auto"
                    >
                        <Calendar className="mr-2 h-4 w-4" />
                        {createLabel}
                    </Button>
                </OperationsDialogFooter>
            </OperationsDialogContent>
        </OperationsDialog>
    );
}
