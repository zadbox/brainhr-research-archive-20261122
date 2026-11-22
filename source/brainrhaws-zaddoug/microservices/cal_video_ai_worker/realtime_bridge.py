from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import threading
import time
from typing import Any, Callable

from .audio import FFmpegAudioPipes, FFmpegCallRecorder, PulseAudioController
from .backend import BrainRHBackendClient
from .config import WorkerSettings


class OpenAIRealtimeAudioBridge:
    def __init__(
        self,
        *,
        settings: WorkerSettings,
        backend: BrainRHBackendClient,
        audio_controller_factory: Callable[[WorkerSettings], PulseAudioController] = PulseAudioController,
        audio_pipes_factory: Callable[[Any], FFmpegAudioPipes] = FFmpegAudioPipes,
        call_recorder_factory: Callable[[WorkerSettings, Any], FFmpegCallRecorder] = FFmpegCallRecorder,
        websocket_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        self.backend = backend
        self.audio_controller_factory = audio_controller_factory
        self.audio_pipes_factory = audio_pipes_factory
        self.call_recorder_factory = call_recorder_factory
        self.websocket_factory = websocket_factory
        self._ws = None
        self._pipes = None
        self._recorder = None
        self._capture_stream = None
        self._playback_stream = None
        self._audio_chunk_bytes = 0
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._appointment_id = ""
        self._interview_id = ""
        self._capture_chunks = 0
        self._capture_non_silent_chunks = 0
        self._playback_bytes = 0
        self._last_capture_log_at = 0.0
        self._handled_call_ids: set[str] = set()
        self._persisted_transcript_keys: set[str] = set()
        self._response_condition = threading.Condition()
        self._response_in_progress = False
        self._realtime_model = self.settings.realtime_model
        self._finalized_event = threading.Event()

    def start(self, appointment: dict[str, Any]) -> None:
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY manquante pour le worker Realtime")

        self._appointment_id = str(appointment["id"])
        self._log(f"starting appointment_id={self._appointment_id}")
        realtime = self.backend.get_worker_realtime_config(self._appointment_id)
        self._interview_id = str(realtime["realtimeInterviewId"])
        session_config = realtime["session"]
        self._realtime_model = str(session_config.get("model") or self.settings.realtime_model)
        self._log(f"loaded config realtime_interview_id={self._interview_id}")

        runtime = self.audio_controller_factory(self.settings).prepare()
        self._audio_chunk_bytes = runtime.chunk_bytes
        self._pipes = self.audio_pipes_factory(runtime)
        self._recorder = self.call_recorder_factory(self.settings, runtime)
        self._recorder.start(str(appointment["id"]))
        if self._recorder.artifact():
            self._log(f"local recording started artifact={self._recorder.artifact()}")
        self._capture_stream = self._pipes.start_capture()
        self._playback_stream = self._pipes.start_playback()
        self._ws = self._connect_websocket()
        self._log(f"websocket connected model={self._realtime_model}")
        self._send({"type": "session.update", "session": session_config})
        self._log("session.update sent")

        self._threads = [
            threading.Thread(target=self._capture_loop, name="brainrh-audio-capture", daemon=True),
            threading.Thread(target=self._receive_loop, name="brainrh-realtime-receiver", daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        time.sleep(0.35)
        self._send_user_text(
            "Démarre maintenant uniquement avec l'accueil humain prévu dans les instructions. "
            "Ne pose pas encore la première question d'évaluation: attends que le candidat réponde ou confirme qu'il est prêt."
        )

    def request_conclusion(self) -> None:
        self.wait_until_idle(timeout=10.0)
        self._send_user_text(
            "Le créneau arrive à sa fin. Conclus naturellement, demande si le candidat a une dernière question, "
            "annonce ensuite la fin de l'entretien puis appelle finalizeInterview."
        )

    def is_finalized(self) -> bool:
        return self._finalized_event.is_set()

    def recording_artifact(self) -> dict[str, object] | None:
        if not self._recorder:
            return None
        return self._recorder.artifact()

    def wait_until_idle(self, *, timeout: float) -> bool:
        deadline = time.monotonic() + max(timeout, 0)
        with self._response_condition:
            while self._response_in_progress and not self._stop_event.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._log("wait_until_idle timed out while response was still in progress")
                    return False
                self._response_condition.wait(timeout=min(remaining, 0.2))

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        self._drain_playback(timeout=remaining)
        return True

    def stop(self) -> None:
        self.wait_until_idle(timeout=15.0)
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._recorder:
            self._recorder.stop()
        if self._pipes:
            self._pipes.stop()
        for thread in self._threads:
            thread.join(timeout=2)
        self._log(
            "stopped "
            f"capture_chunks={self._capture_chunks} "
            f"non_silent_chunks={self._capture_non_silent_chunks} "
            f"playback_bytes={self._playback_bytes}"
        )

    def _connect_websocket(self):
        if self.websocket_factory:
            return self.websocket_factory()
        from websockets.sync.client import connect

        url = f"wss://api.openai.com/v1/realtime?model={self._realtime_model}"
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        try:
            return connect(url, additional_headers=headers, open_timeout=20)
        except TypeError:
            return connect(url, extra_headers=headers, open_timeout=20)

    def _capture_loop(self) -> None:
        chunk_bytes = self._audio_chunk_bytes or self.settings.audio_sample_rate * 2 // 10
        while not self._stop_event.is_set() and self._capture_stream:
            chunk = self._capture_stream.read(chunk_bytes)
            if not chunk:
                continue
            self._capture_chunks += 1
            if any(chunk):
                self._capture_non_silent_chunks += 1
            self._maybe_log_capture_stats()
            try:
                self._send(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(chunk).decode("ascii"),
                    }
                )
            except Exception as exc:
                self._log(f"capture loop send failed: {exc}")
                self._stop_event.set()
                return

    def _receive_loop(self) -> None:
        while not self._stop_event.is_set() and self._ws:
            try:
                raw = self._ws.recv()
            except Exception as exc:
                self._log(f"receive loop stopped: {exc}")
                return
            event = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
            self._handle_event(event)

    def _handle_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type in {"response.audio.delta", "response.output_audio.delta"}:
            delta = event.get("delta")
            if isinstance(delta, str) and self._playback_stream:
                try:
                    decoded = base64.b64decode(delta)
                    self._playback_bytes += len(decoded)
                    self._playback_stream.write(decoded)
                    self._playback_stream.flush()
                except (BrokenPipeError, OSError) as exc:
                    self._log(f"playback write failed: {exc}")
                    return
            return

        if event_type in {"response.audio.done", "response.output_audio.done"}:
            self._log(f"event {event_type}: {self._event_summary(event)}")
            self._finish_playback_segment()
            return

        if event_type in {
            "error",
            "session.created",
            "session.updated",
            "response.created",
            "response.done",
            "response.output_item.done",
            "input_audio_buffer.speech_started",
            "input_audio_buffer.speech_stopped",
            "input_audio_buffer.committed",
            "conversation.item.input_audio_transcription.completed",
            "conversation.item.input_audio_transcription.failed",
        }:
            self._log(f"event {event_type}: {self._event_summary(event)}")

        if event_type == "error":
            self._set_response_in_progress(False)

        if event_type == "response.created":
            self._set_response_in_progress(True)

        if event_type == "input_audio_buffer.speech_started":
            self._clear_playback()

        if event_type == "conversation.item.input_audio_transcription.completed":
            transcript = str(event.get("transcript") or "").strip()
            if transcript:
                self._persist_transcript_turn(
                    speaker="candidate",
                    text=transcript,
                    event=event,
                )
            return

        if event_type == "response.output_item.done":
            for transcript in self._assistant_transcripts_from_output_item(event):
                self._persist_transcript_turn(
                    speaker="assistant",
                    text=transcript,
                    event=event,
                )
            return

        if event_type == "response.function_call_arguments.done":
            self._log(f"tool call args done: {event.get('name')}")
            self._handle_function_call(event)
            return

        if event_type == "response.done":
            self._finish_playback_segment()
            self._set_response_in_progress(False)
            response = event.get("response") if isinstance(event.get("response"), dict) else {}
            for item in response.get("output") or []:
                if isinstance(item, dict) and item.get("type") == "function_call":
                    self._handle_function_call(item, parent_event=event)

    def _handle_function_call(self, item: dict[str, Any], parent_event: dict[str, Any] | None = None) -> None:
        call_id = item.get("call_id") or item.get("callId") or item.get("id")
        name = item.get("name")
        if not call_id or not name:
            return
        call_id = str(call_id)
        if call_id in self._handled_call_ids:
            self._log(f"tool call already handled name={name} call_id={call_id}")
            return
        self._handled_call_ids.add(call_id)
        arguments = item.get("arguments") or "{}"
        self._log(f"submitting tool call name={name} call_id={call_id}")
        try:
            output = self.backend.submit_tool_call(
                self._interview_id,
                appointment_id=self._appointment_id,
                call_id=call_id,
                name=str(name),
                arguments=arguments,
                event=parent_event or item,
            )
            if name == "finalizeInterview":
                self._finalized_event.set()
        except Exception as exc:
            self._log(f"tool call failed name={name} call_id={call_id}: {exc}")
            output = {"outputs": [{"output": {"error": str(exc), "tool": str(name)}}]}
        first_output = (output.get("outputs") or [{}])[0].get("output", output)
        self._log(f"tool call submitted name={name} call_id={call_id}")
        self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(first_output, ensure_ascii=False, default=str),
                },
            }
        )
        self._set_response_in_progress(True)
        self._send({"type": "response.create"})

    def _send_user_text(self, text: str) -> None:
        self._log("sending user text prompt")
        self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            }
        )
        self._set_response_in_progress(True)
        self._send({"type": "response.create"})

    def _set_response_in_progress(self, value: bool) -> None:
        with self._response_condition:
            self._response_in_progress = value
            self._response_condition.notify_all()

    def _finish_playback_segment(self) -> None:
        finish_segment = getattr(self._playback_stream, "finish_segment", None)
        if callable(finish_segment):
            finish_segment()

    def _clear_playback(self) -> None:
        clear = getattr(self._playback_stream, "clear", None)
        if callable(clear):
            clear()
            self._log("candidate speech started: queued assistant audio cleared")

    def _drain_playback(self, *, timeout: float) -> None:
        wait_until_drained = getattr(self._playback_stream, "wait_until_drained", None)
        if callable(wait_until_drained):
            drained = bool(wait_until_drained(timeout=timeout))
            pending_bytes = getattr(self._playback_stream, "pending_bytes", lambda: 0)
            self._log(f"playback drain drained={drained} pending_bytes={pending_bytes()}")

    def _send(self, event: dict[str, Any]) -> None:
        if not self._ws:
            return
        self._ws.send(json.dumps(event, ensure_ascii=False))

    def _persist_transcript_turn(self, *, speaker: str, text: str, event: dict[str, Any]) -> None:
        if not self._interview_id:
            return
        clean_text = text.strip()
        if not clean_text:
            return
        event_id = str(event.get("event_id") or event.get("item_id") or "")
        key_source = f"{speaker}:{event_id}:{clean_text}" if event_id else f"{speaker}:{clean_text}"
        key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()
        if key in self._persisted_transcript_keys:
            return
        self._persisted_transcript_keys.add(key)
        call_id = f"auto-transcript-{key[:24]}"
        try:
            self.backend.submit_tool_call(
                self._interview_id,
                appointment_id=self._appointment_id,
                call_id=call_id,
                name="appendTranscriptTurn",
                arguments={
                    "speaker": speaker,
                    "text": clean_text,
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
                event=event,
            )
            self._log(f"transcript persisted speaker={speaker} call_id={call_id}")
        except Exception as exc:
            self._log(f"transcript persist failed speaker={speaker}: {exc}")

    @staticmethod
    def _assistant_transcripts_from_output_item(event: dict[str, Any]) -> list[str]:
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "message":
            return []
        transcripts: list[str] = []
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            transcript = str(content.get("transcript") or "").strip()
            if transcript:
                transcripts.append(transcript)
        return transcripts

    def _maybe_log_capture_stats(self) -> None:
        now = time.monotonic()
        if now - self._last_capture_log_at < 5:
            return
        self._last_capture_log_at = now
        self._log(
            "capture stats "
            f"chunks={self._capture_chunks} "
            f"non_silent={self._capture_non_silent_chunks} "
            f"playback_bytes={self._playback_bytes}"
        )

    @staticmethod
    def _event_summary(event: dict[str, Any]) -> str:
        if event.get("type") == "error":
            return json.dumps(event.get("error") or event, ensure_ascii=False)[:1000]
        response = event.get("response")
        if isinstance(response, dict):
            summary = {
                "status": response.get("status"),
                "status_details": response.get("status_details"),
                "output_types": [
                    item.get("type")
                    for item in response.get("output", [])
                    if isinstance(item, dict)
                ],
            }
            return json.dumps(summary, ensure_ascii=False, default=str)[:1000]
        item = event.get("item")
        if isinstance(item, dict):
            content = item.get("content")
            return json.dumps(
                {
                    "item_type": item.get("type"),
                    "role": item.get("role"),
                    "content": content,
                    "transcript": item.get("transcript"),
                },
                ensure_ascii=False,
                default=str,
            )[:1000]
        return json.dumps(event, ensure_ascii=False, default=str)[:1000]

    @staticmethod
    def _log(message: str) -> None:
        print(f"[realtime-bridge] {message}", flush=True)
