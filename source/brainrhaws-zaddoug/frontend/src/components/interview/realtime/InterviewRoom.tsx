import { useEffect, useRef, useState } from 'react';
import {
  CheckCheck,
  FileText,
  LoaderCircle,
  Play,
  RefreshCw,
  Sparkles,
  Square,
} from 'lucide-react';
import { realtimeInterviewApi, extractRealtimeClientSecret, type FinalizeRealtimeInterviewResponse, type InterviewPlan, type RealtimePromptPreview, type RealtimeTranscriptTurn, type SubmitToolCallResponse } from '../../../api/realtimeInterview';
import { cn } from '../../../lib/utils';
import { useToast } from '../../../hooks/useToast';
import type { TranslationKey } from '../../../i18n/messages';
import { useI18n } from '../../../i18n/useI18n';
import { Button } from '../../ui/button';
import { Badge } from '../../ui/badge';
import { Section, SystemState } from '../../operations';
import { MicButton } from './MicButton';
import { StatusBadge, type InterviewRoomStatus } from './StatusBadge';
import { TranscriptPanel } from './TranscriptPanel';

interface InterviewRoomProps {
  interviewId: string;
  plan: InterviewPlan;
  className?: string;
  beforeStartSession?: () => void | Promise<void>;
  promptRefreshToken?: string;
  onStatusChange?: (status: InterviewRoomStatus) => void;
  onFinalized?: (result: FinalizeRealtimeInterviewResponse) => void | Promise<void>;
}

interface RealtimeEvent {
  type?: string;
  [key: string]: unknown;
}

interface MutableResponseRef<T> {
  current: T;
}

function resetResponseCreateGate(
  activeRef: MutableResponseRef<boolean>,
  pendingRef: MutableResponseRef<RealtimeEvent | null>
) {
  activeRef.current = false;
  pendingRef.current = null;
}

function requestGatedResponse(
  activeRef: MutableResponseRef<boolean>,
  pendingRef: MutableResponseRef<RealtimeEvent | null>,
  send: (event: RealtimeEvent) => void,
  event: RealtimeEvent = { type: 'response.create' }
) {
  if (activeRef.current) {
    pendingRef.current = event;
    return;
  }

  activeRef.current = true;
  try {
    send(event);
  } catch (error) {
    resetResponseCreateGate(activeRef, pendingRef);
    throw error;
  }
}

function completeGatedResponse(
  activeRef: MutableResponseRef<boolean>,
  pendingRef: MutableResponseRef<RealtimeEvent | null>,
  send: (event: RealtimeEvent) => void
) {
  activeRef.current = false;
  const pendingResponse = pendingRef.current;
  pendingRef.current = null;
  if (pendingResponse) {
    requestGatedResponse(activeRef, pendingRef, send, pendingResponse);
  }
}

interface FunctionCallItem {
  id?: string;
  call_id?: string;
  callId?: string;
  name?: string;
  arguments?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function parseMaybeJson(value: unknown): unknown {
  if (typeof value !== 'string') {
    return value;
  }

  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function stringifyToolOutput(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }

  return JSON.stringify(value ?? {});
}

function normalizeConversationItem(
  callId: string,
  response: SubmitToolCallResponse
): Record<string, unknown> {
  const explicitItem = response.conversationItem ?? response.conversation_item;

  if (isRecord(explicitItem)) {
    if (explicitItem.type === 'conversation.item.create') {
      return explicitItem;
    }

    return {
      type: 'conversation.item.create',
      item: explicitItem,
    };
  }

  const output =
    response.output ??
    response.result ??
    response.toolOutput ??
    response.data ??
    { ok: true };

  return {
    type: 'conversation.item.create',
    item: {
      type: 'function_call_output',
      call_id: callId,
      output: stringifyToolOutput(output),
    },
  };
}

function normalizeFollowupEvents(response: SubmitToolCallResponse): RealtimeEvent[] {
  const events = response.followupEvents ?? response.followup_events ?? [];
  return events.filter(isRecord);
}

function getEventText(event: RealtimeEvent): string | null {
  if (typeof event.transcript === 'string') {
    return event.transcript;
  }

  if (typeof event.text === 'string') {
    return event.text;
  }

  if (typeof event.delta === 'string') {
    return event.delta;
  }

  return null;
}

function describeError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  if (isRecord(error) && typeof error.message === 'string') {
    return error.message;
  }

  return '';
}

export function InterviewRoom({
  interviewId,
  plan,
  className,
  beforeStartSession,
  promptRefreshToken,
  onStatusChange,
  onFinalized,
}: InterviewRoomProps) {
  const toast = useToast();
  const { language, t } = useI18n();
  const [status, setStatus] = useState<InterviewRoomStatus>('idle');
  const [statusDetail, setStatusDetail] = useState<
    { key: TranslationKey } | { text: string }
  >({ key: 'realtime.room.detail.idle' });
  const [transcriptTurns, setTranscriptTurns] = useState<RealtimeTranscriptTurn[]>([]);
  const [starting, setStarting] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [micEnabled, setMicEnabled] = useState(true);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [finalizedSummary, setFinalizedSummary] = useState<FinalizeRealtimeInterviewResponse | null>(null);
  const [promptPreview, setPromptPreview] = useState<RealtimePromptPreview | null>(null);
  const [promptPreviewError, setPromptPreviewError] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const toolCallIdsRef = useRef<Set<string>>(new Set());
  const responseActiveRef = useRef(false);
  const pendingResponseRef = useRef<RealtimeEvent | null>(null);

  const setStatusMessage = (key: TranslationKey) => {
    setStatusDetail({ key });
  };

  const updateTranscriptTurn = (
    turnId: string,
    speaker: RealtimeTranscriptTurn['speaker'],
    text: string,
    mode: 'append' | 'replace',
    isPartial: boolean
  ) => {
    if (!text) {
      return;
    }

    setTranscriptTurns((current) => {
      const nextText = text.trim();
      if (!nextText) {
        return current;
      }

      const index = current.findIndex((turn) => turn.id === turnId);
      if (index === -1) {
        return [
          ...current,
          {
            id: turnId,
            speaker,
            text: nextText,
            ts: new Date().toISOString(),
            isPartial,
          },
        ];
      }

      const existing = current[index];
      const mergedText =
        mode === 'append' ? `${existing.text}${text}`.trim() : nextText;

      const updated = {
        ...existing,
        speaker,
        text: mergedText,
        isPartial,
      };

      const clone = [...current];
      clone[index] = updated;
      return clone;
    });
  };

  const persistTranscriptTurn = async (
    turnId: string,
    speaker: RealtimeTranscriptTurn['speaker'],
    text: string
  ) => {
    const cleanText = text.trim();
    if (!cleanText) {
      return;
    }

    try {
      await realtimeInterviewApi.submitToolCall(interviewId, {
        callId: `persist-${turnId}`,
        name: 'appendTranscriptTurn',
        arguments: {
          speaker,
          text: cleanText,
          ts: new Date().toISOString(),
        },
      });
    } catch (error) {
      console.error('Unable to persist transcript turn:', error);
    }
  };

  const sendRealtimeEvent = (event: RealtimeEvent) => {
    const channel = dataChannelRef.current;
    if (!channel || channel.readyState !== 'open') {
      throw new Error(t('realtime.room.error.channelUnavailable'));
    }

    channel.send(JSON.stringify(event));
  };

  const resetResponseGate = () => {
    resetResponseCreateGate(responseActiveRef, pendingResponseRef);
  };

  const requestResponse = (event: RealtimeEvent = { type: 'response.create' }) => {
    requestGatedResponse(
      responseActiveRef,
      pendingResponseRef,
      sendRealtimeEvent,
      event
    );
  };

  const closeSession = () => {
    resetResponseGate();
    const channel = dataChannelRef.current;
    if (channel) {
      channel.onmessage = null;
      channel.onopen = null;
      channel.onerror = null;
      channel.onclose = null;
      channel.close();
      dataChannelRef.current = null;
    }

    const peerConnection = peerConnectionRef.current;
    if (peerConnection) {
      peerConnection.ontrack = null;
      peerConnection.onconnectionstatechange = null;
      peerConnection.close();
      peerConnectionRef.current = null;
    }

    const localStream = localStreamRef.current;
    if (localStream) {
      localStream.getTracks().forEach((track) => track.stop());
      localStreamRef.current = null;
    }

    if (audioRef.current) {
      audioRef.current.srcObject = null;
    }
  };

  const handleFunctionCall = async (item: FunctionCallItem, event: RealtimeEvent) => {
    const callId = item.call_id ?? item.callId ?? item.id;
    if (!callId || toolCallIdsRef.current.has(callId)) {
      return;
    }

    toolCallIdsRef.current.add(callId);
    setStatus('processing');
    setStatusMessage('realtime.room.detail.synchronizing');

    try {
      const response = await realtimeInterviewApi.submitToolCall(interviewId, {
        callId,
        name: item.name ?? 'unknown_tool',
        arguments: parseMaybeJson(item.arguments),
        rawArguments:
          typeof item.arguments === 'string' ? item.arguments : JSON.stringify(item.arguments ?? {}),
        event,
      });

      const conversationItemEvent = normalizeConversationItem(callId, response);
      sendRealtimeEvent(conversationItemEvent);

      const followupEvents = normalizeFollowupEvents(response);
      let hasResponseCreate = false;

      followupEvents.forEach((followupEvent) => {
        if (followupEvent.type === 'response.create') {
          hasResponseCreate = true;
          requestResponse(followupEvent);
          return;
        }
        sendRealtimeEvent(followupEvent);
      });

      if (!hasResponseCreate) {
        requestResponse();
      }

      setStatus('connected');
      setStatusMessage('realtime.room.detail.resumed');
    } catch (error) {
      const message = describeError(error) || t('realtime.room.error.unexpected');
      setConnectionError(message);
      setStatus('error');
      setStatusDetail({ text: message });

      try {
        sendRealtimeEvent({
          type: 'conversation.item.create',
          item: {
            type: 'function_call_output',
            call_id: callId,
            output: JSON.stringify({ ok: false, error: message }),
          },
        });
        requestResponse();
      } catch {
        // Best effort only. The channel may already be closed.
      }
    }
  };

  const handleRealtimeEvent = async (event: RealtimeEvent) => {
    const eventType = event.type;
    if (!eventType) {
      return;
    }

    switch (eventType) {
      case 'response.created':
        responseActiveRef.current = true;
        return;

      case 'session.created':
      case 'session.updated':
        setStatus('connected');
        setStatusMessage('realtime.room.detail.ready');
        return;

      case 'input_audio_buffer.speech_started':
        setStatus('listening');
        setStatusMessage('realtime.room.detail.candidateSpeaking');
        return;

      case 'input_audio_buffer.speech_stopped':
      case 'conversation.item.input_audio_transcription.completed':
        if (eventType === 'conversation.item.input_audio_transcription.completed') {
          const text = getEventText(event);
          const itemId = typeof event.item_id === 'string' ? event.item_id : `candidate-${Date.now()}`;
          if (text) {
            updateTranscriptTurn(itemId, 'candidate', text, 'replace', false);
            void persistTranscriptTurn(itemId, 'candidate', text);
          }
        }
        setStatus('processing');
        setStatusMessage('realtime.room.detail.analyzing');
        return;

      case 'conversation.item.input_audio_transcription.delta': {
        const text = getEventText(event);
        const itemId = typeof event.item_id === 'string' ? event.item_id : `candidate-${Date.now()}`;
        if (text) {
          updateTranscriptTurn(itemId, 'candidate', text, 'append', true);
        }
        return;
      }

      case 'response.output_audio_transcript.delta':
      case 'response.output_text.delta': {
        const text = getEventText(event);
        const itemId = typeof event.item_id === 'string' ? event.item_id : `assistant-${Date.now()}`;
        if (text) {
          updateTranscriptTurn(itemId, 'assistant', text, 'append', true);
        }
        setStatus('speaking');
        setStatusMessage('realtime.room.detail.assistantSpeaking');
        return;
      }

      case 'response.output_audio_transcript.done':
      case 'response.output_text.done': {
        const text = getEventText(event);
        const itemId = typeof event.item_id === 'string' ? event.item_id : `assistant-${Date.now()}`;
        if (text) {
          updateTranscriptTurn(itemId, 'assistant', text, 'replace', false);
          void persistTranscriptTurn(itemId, 'assistant', text);
        }
        return;
      }

      case 'response.done': {
        try {
          completeGatedResponse(
            responseActiveRef,
            pendingResponseRef,
            sendRealtimeEvent
          );
        } catch (error) {
          const message = describeError(error) || t('realtime.room.error.unexpected');
          setConnectionError(message);
          setStatus('error');
          setStatusDetail({ text: message });
          return;
        }
        const response = isRecord(event.response) ? event.response : null;
        const output = Array.isArray(response?.output) ? response.output : [];
        let hasFunctionCall = false;

        output.forEach((item) => {
          if (!isRecord(item) || item.type !== 'function_call') {
            return;
          }
          hasFunctionCall = true;
          void handleFunctionCall(item as FunctionCallItem, event);
        });

        if (!hasFunctionCall) {
          setStatus('connected');
          setStatusMessage('realtime.room.detail.nextTurn');
        }
        return;
      }

      case 'response.function_call_arguments.done': {
        const item = isRecord(event.item) ? (event.item as FunctionCallItem) : null;
        if (item) {
          void handleFunctionCall(item, event);
        }
        return;
      }

      case 'error': {
        const message =
          isRecord(event.error) && typeof event.error.message === 'string'
            ? event.error.message
            : t('realtime.room.error.unknown');
        resetResponseGate();
        setConnectionError(message);
        setStatus('error');
        setStatusDetail({ text: message });
        return;
      }

      default:
        return;
    }
  };

  const startSession = async () => {
    if (starting) {
      return;
    }

    closeSession();
    toolCallIdsRef.current.clear();
    setStarting(true);
    setConnectionError(null);
    setFinalizedSummary(null);

    try {
      await beforeStartSession?.();
      setStatus('requesting_token');
      setStatusMessage('realtime.room.detail.requestingToken');
      const tokenResponse = await realtimeInterviewApi.getToken(interviewId);
      const ephemeralKey = extractRealtimeClientSecret(tokenResponse);

      setStatus('connecting');
      setStatusMessage('realtime.room.detail.connecting');

      const localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      localStream.getTracks().forEach((track) => {
        track.enabled = micEnabled;
      });
      localStreamRef.current = localStream;

      const peerConnection = new RTCPeerConnection();
      peerConnectionRef.current = peerConnection;

      peerConnection.ontrack = (trackEvent) => {
        if (audioRef.current) {
          audioRef.current.srcObject = trackEvent.streams[0];
        }
      };

      peerConnection.onconnectionstatechange = () => {
        const state = peerConnection.connectionState;
        if (state === 'connected') {
          setStatus('connected');
          setStatusMessage('realtime.room.detail.audioConnected');
        } else if (state === 'connecting') {
          setStatus('connecting');
          setStatusMessage('realtime.room.detail.negotiating');
        } else if (state === 'disconnected' || state === 'failed') {
          resetResponseGate();
          setStatus('error');
          setStatusMessage('realtime.room.detail.interrupted');
        } else if (state === 'closed') {
          resetResponseGate();
          setStatus('disconnected');
          setStatusMessage('realtime.room.detail.closed');
        }
      };

      localStream.getTracks().forEach((track) => {
        peerConnection.addTrack(track, localStream);
      });

      const dataChannel = peerConnection.createDataChannel('oai-events');
      dataChannelRef.current = dataChannel;

      dataChannel.onmessage = (messageEvent) => {
        try {
          const parsed = JSON.parse(String(messageEvent.data)) as RealtimeEvent;
          void handleRealtimeEvent(parsed);
        } catch (error) {
          console.error('Unable to parse realtime event:', error);
        }
      };

      dataChannel.onopen = () => {
        setStatus('connected');
        setStatusMessage('realtime.room.detail.open');

        try {
          sendRealtimeEvent({
            type: 'conversation.item.create',
            item: {
              type: 'message',
              role: 'user',
              content: [
                {
                  type: 'input_text',
                  text: 'Start the interview now with a very brief greeting, then ask the first question.',
                },
              ],
            },
          });
          requestResponse();
        } catch (error) {
          const message = describeError(error) || t('realtime.room.error.unexpected');
          setConnectionError(message);
          setStatus('error');
          setStatusDetail({ text: message });
        }
      };

      dataChannel.onerror = () => {
        resetResponseGate();
        setStatus('error');
        setStatusMessage('realtime.room.detail.channelError');
      };

      dataChannel.onclose = () => {
        resetResponseGate();
        setStatus('disconnected');
        setStatusMessage('realtime.room.detail.closed');
      };

      const offer = await peerConnection.createOffer();
      await peerConnection.setLocalDescription(offer);

      const response = await fetch('https://api.openai.com/v1/realtime/calls', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${ephemeralKey}`,
          'Content-Type': 'application/sdp',
        },
        body: offer.sdp ?? '',
      });

      if (!response.ok) {
        throw new Error(`${t('realtime.room.error.rejected')} (${response.status}).`);
      }

      const answerSdp = await response.text();
      await peerConnection.setRemoteDescription({
        type: 'answer',
        sdp: answerSdp,
      });

      toast.success(t('realtime.room.toast.opened'));
    } catch (error) {
      closeSession();
      const rawMessage = describeError(error);
      const message = rawMessage === 'The backend did not return a usable Realtime client secret.'
        ? t('realtime.room.error.missingSecret')
        : rawMessage || t('realtime.room.error.unexpected');
      setConnectionError(message);
      setStatus('error');
      setStatusDetail({ text: message });
      toast.error(t('realtime.room.toast.openError'), message);
    } finally {
      setStarting(false);
    }
  };

  const disconnectSession = () => {
    closeSession();
    if (status !== 'completed') {
      setStatus('disconnected');
      setStatusMessage('realtime.room.detail.stopped');
    }
  };

  const toggleMic = () => {
    const nextEnabled = !micEnabled;
    setMicEnabled(nextEnabled);

    const localStream = localStreamRef.current;
    if (localStream) {
      localStream.getAudioTracks().forEach((track) => {
        track.enabled = nextEnabled;
      });
    }
  };

  const finalizeInterview = async () => {
    if (finalizing) {
      return;
    }

    setFinalizing(true);
    setStatus('finalizing');
    setStatusMessage('realtime.room.detail.finalizing');

    try {
      disconnectSession();
      const result = await realtimeInterviewApi.finalize(interviewId);
      setFinalizedSummary(result);
      setStatus('completed');
      setStatusMessage('realtime.room.detail.finalized');
      toast.success(t('realtime.room.toast.finalized'));
      await onFinalized?.(result);
    } catch (error) {
      const message = describeError(error) || t('realtime.room.error.unexpected');
      setConnectionError(message);
      setStatus('error');
      setStatusDetail({ text: message });
      toast.error(t('realtime.room.toast.finalizeError'), message);
    } finally {
      setFinalizing(false);
    }
  };

  useEffect(() => {
    onStatusChange?.(status);
  }, [status, onStatusChange]);

  const closeSessionRef = useRef(closeSession);
  closeSessionRef.current = closeSession;

  useEffect(() => {
    return () => {
      closeSessionRef.current();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    setPromptPreview(null);
    setPromptPreviewError(null);
    realtimeInterviewApi.getPrompt(interviewId)
      .then((preview) => {
        if (!cancelled) {
          setPromptPreview(preview);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setPromptPreviewError(describeError(error) || t('realtime.room.error.unexpected'));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [interviewId, promptRefreshToken, t]);

  const transcriptCount = transcriptTurns.filter((turn) => !turn.isPartial).length;
  const stageCount = plan.stages.length;
  const summaryText =
    typeof finalizedSummary?.summary === 'string'
      ? finalizedSummary.summary
      : isRecord(finalizedSummary?.summary)
        ? String(finalizedSummary?.summary.summaryText ?? '')
        : isRecord(finalizedSummary?.summaryData)
          ? String(finalizedSummary.summaryData.summaryText ?? '')
          : '';

  return (
    <div className={cn('space-y-6', className)}>
      <audio ref={audioRef} autoPlay className="hidden" />

      <Section
        title={t('realtime.room.title')}
        description={t('realtime.room.description')}
        divided={false}
        actionsLabel={t('realtime.room.actions')}
        actions={
          <div className="grid w-full gap-2 sm:flex sm:w-auto sm:flex-wrap sm:justify-end">
            <MicButton
              disabled={status === 'idle' || status === 'connecting' || starting}
              muted={!micEnabled}
              busy={starting}
              onToggle={toggleMic}
            />
            <Button onClick={startSession} disabled={starting} className="min-h-11 w-full sm:w-auto sm:min-w-36">
              {starting ? (
                <>
                  <LoaderCircle aria-hidden="true" className="h-4 w-4 motion-safe:animate-spin" />
                  {t('realtime.room.action.connecting')}
                </>
              ) : status === 'connected' || status === 'listening' || status === 'speaking' || status === 'processing' ? (
                <>
                  <RefreshCw aria-hidden="true" className="h-4 w-4" />
                  {t('realtime.room.action.reconnect')}
                </>
              ) : (
                <>
                  <Play aria-hidden="true" className="h-4 w-4" />
                  {t('realtime.room.action.launch')}
                </>
              )}
            </Button>
            <Button
              variant="outline"
              onClick={disconnectSession}
              disabled={starting || status === 'idle' || status === 'disconnected'}
              className="min-h-11 w-full sm:w-auto"
            >
              <Square aria-hidden="true" className="h-4 w-4" />
              {t('realtime.room.action.stop')}
            </Button>
            <Button
              variant="secondary"
              onClick={finalizeInterview}
              disabled={finalizing || status === 'idle'}
              className="min-h-11 w-full sm:w-auto"
            >
              {finalizing ? (
                <>
                  <LoaderCircle aria-hidden="true" className="h-4 w-4 motion-safe:animate-spin" />
                  {t('realtime.room.action.finalizing')}
                </>
              ) : (
                <>
                  <CheckCheck aria-hidden="true" className="h-4 w-4" />
                  {t('realtime.room.action.finalize')}
                </>
              )}
            </Button>
          </div>
        }
      >
        <div className="flex min-w-0 flex-col gap-5 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4 sm:p-5">
          <div className="flex flex-wrap items-center gap-3">
            <Sparkles aria-hidden="true" className="h-5 w-5 text-[var(--brain-ops-accent)]" />
            <StatusBadge
              status={status}
              detail={'key' in statusDetail ? t(statusDetail.key) : statusDetail.text}
            />
          </div>
          <div className="grid gap-px overflow-hidden border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-border)] md:grid-cols-2">
            <div className="bg-[var(--brain-ops-surface)] p-4">
              <p className="text-xs uppercase tracking-[0.12em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                {t('realtime.room.activePlan')}
              </p>
              <p className="mt-2 text-sm font-medium text-[var(--brain-ops-text)]">{plan.roleTitle}</p>
              <p className="mt-1 text-xs text-[var(--brain-ops-text-muted)]">
                {stageCount} {t('realtime.room.plannedStages')}
              </p>
            </div>
            <div className="bg-[var(--brain-ops-surface)] p-4">
              <p className="text-xs uppercase tracking-[0.12em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                {t('realtime.room.transcriptMetric')}
              </p>
              <p className="mt-2 text-sm font-medium text-[var(--brain-ops-text)]">
                {transcriptCount} {t('realtime.room.consolidatedTurns')}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge variant="outline">{plan.languageHint ?? 'auto'}</Badge>
                <Badge variant="outline">
                  {micEnabled ? t('realtime.room.mic.open') : t('realtime.room.mic.mutedShort')}
                </Badge>
              </div>
            </div>
          </div>
        </div>
      </Section>

      {connectionError ? (
        <SystemState kind="error" title={t('realtime.room.sessionError')} description={connectionError} />
      ) : null}

      <details className="rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] p-4 text-sm">
        <summary className="flex cursor-pointer items-center gap-2 font-medium text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
          <FileText aria-hidden="true" className="h-4 w-4" />
          {t('realtime.room.technicalDetails')}
        </summary>
        <div className="mt-4 space-y-4 border-t border-[color:var(--brain-ops-border)] pt-4">
          <p className="break-all text-xs text-[var(--brain-ops-text-muted)]">
            {t('realtime.room.interviewId')}: {interviewId}
          </p>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">{t('realtime.room.model')}: {promptPreview?.model ?? t('realtime.room.loading')}</Badge>
            <Badge variant="outline">{t('realtime.room.voice')}: {promptPreview?.voice ?? t('realtime.room.loading')}</Badge>
            <Badge variant="outline">
              {t('realtime.room.vad')}: {String(promptPreview?.turnDetection?.type ?? t('realtime.room.loading'))}
            </Badge>
            <Badge variant="outline">
              {t('realtime.room.interrupt')}: {String(promptPreview?.turnDetection?.interrupt_response ?? t('realtime.room.loading'))}
            </Badge>
          </div>
          {promptPreviewError ? (
            <p role="alert" className="text-sm text-[var(--brain-ops-danger)]">{promptPreviewError}</p>
          ) : (
            <div className="border-l-2 border-[color:var(--brain-ops-border-strong)] pl-3 text-sm text-[var(--brain-ops-text-muted)]">
              {t('realtime.room.technicalNotice')}
            </div>
          )}
        </div>
      </details>

      <TranscriptPanel turns={transcriptTurns} />

      {finalizedSummary ? (
        <Section title={t('realtime.summary.title')} description={t('realtime.summary.description')}>
          <div className="space-y-4">
            <div className="rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4 text-sm leading-6">
              {summaryText || t('realtime.summary.empty')}
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4">
                <p className="text-xs uppercase tracking-[0.12em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t('realtime.summary.signals')}
                </p>
                <div className="mt-3 space-y-2">
                  {(finalizedSummary.notableSignals ?? finalizedSummary.notable_signals ?? []).length === 0 ? (
                    <p className="text-sm text-[var(--brain-ops-text-muted)]">{t('realtime.summary.noSignals')}</p>
                  ) : (
                    (finalizedSummary.notableSignals ?? finalizedSummary.notable_signals ?? []).map((signal) => (
                      <div key={`${signal.type}-${signal.createdAt}`} className="border-t border-[color:var(--brain-ops-border)] pt-3 first:border-t-0 first:pt-0">
                        <div className="flex items-center justify-between gap-3">
                          <Badge variant="outline">{signal.type}</Badge>
                          <span className="text-xs text-[var(--brain-ops-text-muted)]">
                            {new Date(signal.createdAt).toLocaleTimeString(language === 'fr' ? 'fr-FR' : 'en-US', {
                              hour: '2-digit',
                              minute: '2-digit',
                            })}
                          </span>
                        </div>
                        <p className="mt-2 text-sm">{signal.text}</p>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4">
                <p className="text-xs uppercase tracking-[0.12em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t('realtime.summary.turns')}
                </p>
                <p className="mt-3 text-3xl font-semibold">
                  {(finalizedSummary.transcriptTurns ?? finalizedSummary.transcript_turns ?? transcriptTurns).length}
                </p>
                <p className="mt-2 text-sm text-[var(--brain-ops-text-muted)]">
                  {t('realtime.summary.optionalScore')}:{' '}
                  {typeof finalizedSummary.score === 'number' ? finalizedSummary.score : t('realtime.summary.notProvided')}
                </p>
              </div>
            </div>
          </div>
        </Section>
      ) : null}
    </div>
  );
}
