import { apiClient } from './client';

export type RealtimeInterviewLanguageHint = 'fr' | 'en' | 'ar' | 'auto';

export interface InterviewStage {
  id: string;
  label: string;
  objective: string;
  mustCover: string[];
  sampleQuestions: string[];
  followupTriggers: string[];
}

export interface InterviewPlan {
  languageHint?: RealtimeInterviewLanguageHint;
  roleTitle: string;
  candidateName: string;
  jobSummary: string;
  candidateSummary: string;
  stages: InterviewStage[];
  scoringRubric: Array<{
    category: string;
    criteria: string[];
  }>;
  registryContext?: BrainRHRealtimeContext | null;
}

export interface RealtimeSignal {
  type: 'strength' | 'risk' | 'clarification' | 'followup';
  text: string;
  createdAt: string;
}

export interface RealtimeTranscriptTurn {
  id?: string;
  speaker: 'candidate' | 'assistant';
  text: string;
  ts: string;
  isPartial?: boolean;
}

export interface InterviewRuntimeState {
  interviewId: string;
  currentStageId: string;
  coveredItems: string[];
  notableSignals: RealtimeSignal[];
  temporaryBranch?: {
    topic: string;
    reason: string;
    remainingQuestions: number;
  } | null;
  transcriptTurns: RealtimeTranscriptTurn[];
}

export interface BrainRHRealtimeContext {
  projectId?: string | null;
  candidateId?: string | null;
  matchingId?: string | null;
  interviewSheetId?: string | null;
  source?: string | null;
  candidateEmail?: string | null;
  candidatePhone?: string | null;
}

export interface SetupRealtimeInterviewInput {
  candidateName?: string;
  cvText?: string;
  jobDescriptionText?: string;
  mode?: 'manual' | 'registry' | 'canonical';
  projectId?: string;
  jobId?: string;
  candidateId?: string;
  matchingId?: string;
  interviewSheetId?: string;
  aiPlanInstructions?: string;
  languageHint: RealtimeInterviewLanguageHint;
}

export interface SetupRealtimeInterviewResponse {
  interviewId: string;
  plan: InterviewPlan | null;
  runtimeState?: InterviewRuntimeState | null;
  registryContext?: BrainRHRealtimeContext | null;
  brainrhContext?: BrainRHRealtimeContext | null;
  interviewSheetId?: string | null;
  preparationState?: 'pending' | 'ready' | 'failed';
  retryable?: boolean;
  message?: string;
}

export interface RealtimeInterviewContextResponse {
  interviewId: string;
  candidateName: string;
  languageHint?: RealtimeInterviewLanguageHint;
  cvText: string;
  jobDescriptionText: string;
  plan: InterviewPlan | null;
  status: string;
  preparationState?: 'pending' | 'ready' | 'failed';
  registryContext?: BrainRHRealtimeContext | null;
}

export interface UpdateRealtimeInterviewPlanResponse {
  interviewId: string;
  plan: InterviewPlan;
  runtimeState?: InterviewRuntimeState | null;
  registryContext?: BrainRHRealtimeContext | null;
}

export interface RealtimeClientSecret {
  value: string;
  expires_at?: number | string;
  expiresAt?: number | string;
}

export interface RealtimeTokenResponse {
  value?: string;
  client_secret?: RealtimeClientSecret | string;
  clientSecret?: RealtimeClientSecret | string;
  session_id?: string;
  sessionId?: string;
  expires_at?: number | string;
  expiresAt?: number | string;
  prompt?: string;
  session?: Record<string, unknown>;
}

export interface RealtimePromptPreview {
  interviewId: string;
  prompt?: string;
  model?: string;
  voice?: string;
  turnDetection?: Record<string, unknown> | null;
  transcription?: Record<string, unknown> | null;
}

export interface SubmitToolCallInput {
  callId: string;
  name: string;
  arguments: unknown;
  rawArguments?: string;
  event?: unknown;
}

export interface SubmitToolCallResponse {
  output?: unknown;
  result?: unknown;
  toolOutput?: unknown;
  data?: unknown;
  outputs?: Array<{
    callId?: string | null;
    name?: string;
    output?: unknown;
  }>;
  conversationItem?: Record<string, unknown>;
  conversation_item?: Record<string, unknown>;
  followupEvents?: Array<Record<string, unknown>>;
  followup_events?: Array<Record<string, unknown>>;
}

export interface FinalizeRealtimeInterviewResponse {
  interviewId?: string;
  summary?: string | Record<string, unknown>;
  summaryData?: Record<string, unknown>;
  overallAppreciation?: string;
  transcriptTurns?: RealtimeTranscriptTurn[];
  transcript_turns?: RealtimeTranscriptTurn[];
  notableSignals?: RealtimeSignal[];
  notable_signals?: RealtimeSignal[];
  score?: number | null;
  registryContext?: BrainRHRealtimeContext | null;
  brainrhContext?: BrainRHRealtimeContext | null;
  interviewSheetSync?: {
    interviewSheetId?: string | null;
    updatedAt?: string | null;
    error?: string | null;
  } | null;
}

function unwrapClientSecret(secret?: RealtimeClientSecret | string): string | null {
  if (!secret) {
    return null;
  }

  if (typeof secret === 'string') {
    return secret;
  }

  return secret.value || null;
}

export function extractRealtimeClientSecret(token: RealtimeTokenResponse): string {
  const value =
    token.value ||
    unwrapClientSecret(token.client_secret) ||
    unwrapClientSecret(token.clientSecret);

  if (!value) {
    throw new Error('The backend did not return a usable Realtime client secret.');
  }

  return value;
}

export const realtimeInterviewApi = {
  setup: async (input: SetupRealtimeInterviewInput): Promise<SetupRealtimeInterviewResponse> => {
    const response = await apiClient.post<SetupRealtimeInterviewResponse>(
      '/realtime-interviews/setup',
      input
    );
    return response.data;
  },

  getToken: async (interviewId: string): Promise<RealtimeTokenResponse> => {
    const response = await apiClient.get<RealtimeTokenResponse>(
      `/realtime-interviews/${interviewId}/token`
    );
    return response.data;
  },

  getPrompt: async (interviewId: string): Promise<RealtimePromptPreview> => {
    const response = await apiClient.get<RealtimePromptPreview>(
      `/realtime-interviews/${interviewId}/prompt`
    );
    return response.data;
  },

  getContext: async (interviewId: string): Promise<RealtimeInterviewContextResponse> => {
    const response = await apiClient.get<RealtimeInterviewContextResponse>(
      `/realtime-interviews/${interviewId}`
    );
    return response.data;
  },

  updatePlan: async (
    interviewId: string,
    plan: InterviewPlan
  ): Promise<UpdateRealtimeInterviewPlanResponse> => {
    const response = await apiClient.put<UpdateRealtimeInterviewPlanResponse>(
      `/realtime-interviews/${interviewId}/plan`,
      { plan }
    );
    return response.data;
  },

  submitToolCall: async (
    interviewId: string,
    input: SubmitToolCallInput
  ): Promise<SubmitToolCallResponse> => {
    const response = await apiClient.post<SubmitToolCallResponse>(
      `/realtime-interviews/${interviewId}/tool-calls`,
      {
        calls: [
          {
            callId: input.callId,
            name: input.name,
            arguments: input.arguments,
            rawArguments: input.rawArguments,
            event: input.event,
          },
        ],
      }
    );
    const firstOutput = response.data.outputs?.[0]?.output;
    return {
      ...response.data,
      output: firstOutput ?? response.data.output,
      result: firstOutput ?? response.data.result,
    };
  },

  finalize: async (interviewId: string): Promise<FinalizeRealtimeInterviewResponse> => {
    const response = await apiClient.post<FinalizeRealtimeInterviewResponse>(
      `/realtime-interviews/${interviewId}/finalize`
    );
    return response.data;
  },
};
