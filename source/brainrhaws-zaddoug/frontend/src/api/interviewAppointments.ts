import { apiClient } from './client';

export type InterviewAppointmentStatus =
  | 'scheduled'
  | 'waiting_candidate'
  | 'in_progress'
  | 'paused'
  | 'wrapping_up'
  | 'completed'
  | 'no_show'
  | 'cancelled'
  | 'failed';

/** Qui conduit l'entretien : l'agent IA BrainRH ou un recruteur. */
export type InterviewMode = 'ai' | 'human';
export type HumanMeetingFormat = 'video' | 'phone' | 'on_site';
export type HumanInterviewOutcome = 'completed' | 'no_show';

export interface CreateInterviewAppointmentInput {
  start_at: string;
  end_at?: string | null;
  duration_minutes?: number;
  candidate_name?: string | null;
  candidate_email?: string | null;
  candidate_timezone?: string;
  language_hint?: 'fr' | 'en' | 'ar' | 'auto';
  scheduler_notes?: string | null;
  booking_fields_responses?: Record<string, unknown>;
  metadata?: Record<string, string>;
}

export interface CreateHumanInterviewAppointmentInput {
  start_at: string;
  end_at?: string | null;
  duration_minutes?: number;
  candidate_name?: string | null;
  candidate_email?: string | null;
  candidate_timezone?: string;
  interviewer_name?: string | null;
  interviewer_email?: string | null;
  meeting_format: HumanMeetingFormat;
  meeting_url?: string | null;
  meeting_location?: string | null;
  scheduler_notes?: string | null;
  send_invitation: boolean;
  invitation_language: 'fr' | 'en';
}

export type ScheduleInterviewRequest =
  | { mode: 'ai'; input: CreateInterviewAppointmentInput }
  | { mode: 'human'; input: CreateHumanInterviewAppointmentInput };

export interface ScheduledInterviewResult {
  appointment: InterviewAppointment;
  invitationWarning?: string;
}

export interface InterviewInvitationState {
  status: 'pending' | 'not_requested' | 'sent' | 'not_configured' | 'failed';
  sent_at?: string | null;
  language?: 'fr' | 'en';
  cancellation?: { status: InterviewInvitationState['status'] };
  [key: string]: unknown;
}

export interface InterviewAppointment {
  id: string;
  interview_sheet_id: string;
  /** Absent pour un entretien recruteur : aucune session IA n'est créée. */
  realtime_interview_id: string | null;
  interview_mode: InterviewMode;
  interviewer_name: string | null;
  interviewer_email: string | null;
  meeting_format: HumanMeetingFormat | null;
  meeting_url: string | null;
  meeting_location: string | null;
  provider: string;
  status: InterviewAppointmentStatus;
  active_slot?: string | null;
  start_at: string;
  end_at: string;
  candidate_name: string;
  candidate_email: string;
  candidate_timezone: string;
  ai_interviewer_name: string;
  calcom_booking_uid: string | null;
  calcom_booking_id: string | null;
  calcom_event_type_id: number | null;
  calcom_event_type_slug: string | null;
  calcom_video_url: string | null;
  booking: Record<string, unknown>;
  booking_references: Array<Record<string, unknown>>;
  conferencing_sessions: Array<Record<string, unknown>>;
  recordings: InterviewRecordingArtifact[];
  transcripts: unknown[];
  worker_state: Record<string, unknown>;
  artifact_data: Record<string, unknown>;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface InterviewRecordingArtifact {
  id?: string | null;
  uid?: string | null;
  title?: string | null;
  name?: string | null;
  roomName?: string | null;
  provider?: string | null;
  type?: string | null;
  status?: string | null;
  url?: string | null;
  link?: string | null;
  view_url?: string | null;
  download_url?: string | null;
  downloadUrl?: string | null;
  downloadLink?: string | null;
  recordingUrl?: string | null;
  size_bytes?: number | null;
  duration?: number | string | null;
  duration_seconds?: number | string | null;
  created_at?: string | null;
  uploaded_at?: string | null;
  started_at?: string | null;
  stopped_at?: string | null;
  video_size?: string | null;
  resolution?: string | null;
  [key: string]: unknown;
}

export interface CreateInterviewAppointmentResponse {
  appointment: InterviewAppointment;
  booking: Record<string, unknown>;
  realtime: {
    interviewId: string;
    plan: Record<string, unknown>;
  };
}

export interface CreateHumanInterviewAppointmentResponse {
  appointment: InterviewAppointment;
  invitation: InterviewInvitationState;
  invitationWarning?: string;
}

export interface CancelInterviewAppointmentResponse {
  appointment: InterviewAppointment;
  providerCancel: Record<string, unknown>;
  providerWarning?: string;
  invitationWarning?: string;
}

export function appointmentInvitation(appointment: InterviewAppointment): InterviewInvitationState | null {
  const invitation = appointment.artifact_data?.invitation;
  return invitation && typeof invitation === 'object' ? invitation as InterviewInvitationState : null;
}

export const interviewAppointmentsApi = {
  createFromSheet: async (
    sheetId: string,
    input: CreateInterviewAppointmentInput
  ): Promise<CreateInterviewAppointmentResponse> => {
    const response = await apiClient.post<CreateInterviewAppointmentResponse>(
      `/interview-appointments/from-sheet/${sheetId}/calcom`,
      input
    );
    return response.data;
  },

  createHumanFromSheet: async (
    sheetId: string,
    input: CreateHumanInterviewAppointmentInput
  ): Promise<CreateHumanInterviewAppointmentResponse> => {
    const response = await apiClient.post<CreateHumanInterviewAppointmentResponse>(
      `/interview-appointments/from-sheet/${sheetId}/human`,
      input
    );
    return response.data;
  },

  /** Planifie selon le mode choisi ; l'IA garde son parcours Cal.com inchangé. */
  scheduleFromSheet: async (
    sheetId: string,
    request: ScheduleInterviewRequest
  ): Promise<ScheduledInterviewResult> => {
    if (request.mode === 'human') {
      const created = await interviewAppointmentsApi.createHumanFromSheet(sheetId, request.input);
      return { appointment: created.appointment, invitationWarning: created.invitationWarning };
    }
    const created = await interviewAppointmentsApi.createFromSheet(sheetId, request.input);
    return { appointment: created.appointment };
  },

  recordOutcome: async (
    appointmentId: string,
    outcome: HumanInterviewOutcome
  ): Promise<InterviewAppointment> => {
    const response = await apiClient.post<{ appointment: InterviewAppointment }>(
      `/interview-appointments/${appointmentId}/outcome`,
      { outcome }
    );
    return response.data.appointment;
  },

  get: async (appointmentId: string): Promise<InterviewAppointment> => {
    const response = await apiClient.get<InterviewAppointment>(`/interview-appointments/${appointmentId}`);
    return response.data;
  },

  cancel: async (appointmentId: string, reason?: string): Promise<CancelInterviewAppointmentResponse> => {
    const response = await apiClient.post<CancelInterviewAppointmentResponse>(
      `/interview-appointments/${appointmentId}/cancel`,
      { reason: reason || null }
    );
    return response.data;
  },
};
