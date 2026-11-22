from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .audio import PulseAudioController
from .config import WorkerSettings


JOIN_BUTTON_RE = re.compile(r"(join|rejoindre|participer|enter|continue|start)", re.I)


def detect_candidate_count(snapshot: dict[str, object]) -> int:
    if "candidateCount" in snapshot:
        return int(snapshot.get("candidateCount") or 0)
    participant_count = int(snapshot.get("participantCount") or 0)
    text = str(snapshot.get("text") or "").lower()
    if "only you" in text or "vous seul" in text:
        return 0
    return max(0, participant_count - 1)


class PlaywrightCalVideoRoomAdapter:
    def __init__(
        self,
        settings: WorkerSettings,
        *,
        audio_controller_factory: Callable[[WorkerSettings], PulseAudioController] = PulseAudioController,
    ):
        self.settings = settings
        self.audio_controller_factory = audio_controller_factory
        self._audio_runtime = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._candidate_present = False
        self._debug_dir = Path(os.getenv("CAL_VIDEO_DEBUG_DIR", "/tmp/brainrh-cal-video-debug"))
        self._idle_audio_process = None

    def join(self, video_url: str, display_name: str) -> None:
        from playwright.sync_api import sync_playwright

        self._log(f"joining {video_url}")
        self._audio_runtime = self.audio_controller_factory(self.settings).prepare()
        self._start_idle_audio()
        self._playwright = sync_playwright().start()
        chromium = self._playwright.chromium
        launch_kwargs = {
            "headless": self.settings.headless,
            "ignore_default_args": ["--mute-audio"],
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],
        }
        if self.settings.chromium_executable_path:
            launch_kwargs["executable_path"] = self.settings.chromium_executable_path
        self._browser = chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(
            permissions=["microphone", "camera"],
            viewport={"width": 1280, "height": 720},
        )
        self._page = self._context.new_page()
        self._page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
        self._capture_debug("01-loaded")
        self._fill_display_name(display_name)
        self._capture_debug("02-name-filled")
        self._click_join_buttons()
        daily_join = self._extract_daily_join()
        self._join_daily_call_object(daily_join["room_url"], daily_join["token"], display_name)
        self._capture_debug("03-daily-sdk-joined")
        self._log("joined Daily room confirmed")

    def wait_for_candidate(self, deadline: datetime) -> bool:
        while datetime.now(timezone.utc) < deadline:
            snapshot = self._snapshot()
            candidate_count = detect_candidate_count(snapshot)
            self._log(
                "candidate poll "
                f"candidate_count={candidate_count} participant_count={snapshot.get('participantCount')}"
            )
            if candidate_count > 0:
                self._candidate_present = True
                return True
            time.sleep(self.settings.poll_interval_seconds)
        return False

    def next_room_event(self, deadline: datetime) -> str:
        if datetime.now(timezone.utc) >= deadline:
            return "deadline"
        count = detect_candidate_count(self._snapshot())
        if count > 0 and not self._candidate_present:
            self._candidate_present = True
            return "candidate_rejoined"
        if count == 0 and self._candidate_present:
            self._candidate_present = False
            return "candidate_left"
        return "idle"

    def leave(self) -> None:
        try:
            if self._page:
                self._leave_daily_call_object()
        finally:
            self.stop_idle_audio()
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()

    def _fill_display_name(self, display_name: str) -> None:
        assert self._page is not None
        locators = [
            self._page.get_by_placeholder("Your name", exact=True),
            self._page.get_by_placeholder("Votre nom", exact=True),
            self._page.locator("input[type='text']").first,
        ]
        for locator in locators:
            try:
                locator.fill(display_name, timeout=8000)
                return
            except Exception:
                continue
        raise RuntimeError("Unable to fill Cal Video display name")

    def _click_join_buttons(self) -> None:
        assert self._page is not None
        for _ in range(20):
            if self._daily_iframe_src():
                return
            clicked = False
            for frame in self._page.frames:
                try:
                    button = frame.get_by_role("button", name=JOIN_BUTTON_RE).first
                    if button.count() > 0:
                        button.click(timeout=5000)
                        clicked = True
                        self._log("clicked join-like button")
                        time.sleep(1)
                        break
                except Exception:
                    continue
            if self._daily_iframe_src():
                return
            if not clicked:
                time.sleep(1)

    def _daily_iframe_src(self) -> str:
        assert self._page is not None
        try:
            iframe_src = str(
                self._page.evaluate(
                    """
                    () => {
                      const iframe = document.querySelector('iframe[src*="daily.co"]');
                      return iframe ? iframe.src : "";
                    }
                    """
                )
                or ""
            )
        except Exception:
            iframe_src = ""
        if iframe_src:
            return iframe_src
        for frame in self._page.frames:
            if "daily.co" in frame.url:
                return frame.url
        return ""

    def _extract_daily_join(self) -> dict[str, str]:
        deadline = time.monotonic() + 30
        iframe_src = ""
        while time.monotonic() < deadline:
            iframe_src = self._daily_iframe_src()
            if iframe_src:
                break
            time.sleep(1)
        if not iframe_src:
            self._capture_debug("daily-iframe-missing")
            raise RuntimeError("Daily iframe URL was not available after Cal Video guest join")

        parsed = urlparse(iframe_src)
        token = parse_qs(parsed.query).get("t", [""])[0]
        if not parsed.scheme or not parsed.netloc or not parsed.path or not token:
            self._capture_debug("daily-token-missing")
            raise RuntimeError("Daily room URL/token missing from Cal Video iframe")
        room_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        self._log(f"Daily room extracted: {room_url}")
        return {"room_url": room_url, "token": token}

    def _join_daily_call_object(self, room_url: str, token: str, display_name: str) -> None:
        assert self._page is not None
        self._page.set_content(
            """
            <html>
              <head>
                <style>
                  html, body {
                    width: 100%;
                    height: 100%;
                    margin: 0;
                    background: #050505;
                    color: #f8f8f8;
                    font-family: Inter, Arial, sans-serif;
                    overflow: hidden;
                  }
                  #remote-media {
                    display: grid;
                    width: 100vw;
                    height: 100vh;
                    place-items: center;
                    background: #050505;
                  }
                  video {
                    width: 100vw;
                    height: 100vh;
                    object-fit: contain;
                    background: #050505;
                  }
                  .placeholder {
                    display: grid;
                    place-items: center;
                    width: 100vw;
                    height: 100vh;
                    color: rgba(248, 248, 248, 0.72);
                    font-size: 24px;
                    letter-spacing: 0;
                  }
                  audio {
                    display: none;
                  }
                </style>
              </head>
              <body>
                <div id="remote-media"><div class="placeholder">En attente de la vidéo candidat</div></div>
                <div id="remote-audio"></div>
              </body>
            </html>
            """
        )
        self._page.add_script_tag(url="https://unpkg.com/@daily-co/daily-js@0.83.1/dist/daily-iframe.js")
        state = self._page.evaluate(
            """
            async ({ roomUrl, token, displayName }) => {
              window.__brainrhDailyEvents = [];
              window.__brainrhRemoteAudioElements = {};
              window.__brainrhRemoteVideoElements = {};
              window.__brainrhAiDisplayName = displayName;
              const Daily = window.DailyIframe || window.Daily;
              const existing = Daily.getCallInstance && Daily.getCallInstance();
              if (existing) {
                await existing.destroy();
              }
              const call = Daily.createCallObject({ audioSource: true, videoSource: false });
              window.__brainrhDailyCall = call;

              const participantSummary = (participant) => {
                const audioTrack = participant && participant.tracks && participant.tracks.audio;
                return participant
                  ? {
                      session_id: participant.session_id,
                      local: participant.local,
                      user_name: participant.user_name,
                      audio: participant.audio,
                      video: participant.video,
                      audioState: audioTrack && audioTrack.state,
                      audioSubscribed: audioTrack && audioTrack.subscribed,
                      audioTrackReady: Boolean(
                        (audioTrack && (audioTrack.persistentTrack || audioTrack.track)) ||
                          participant.audioTrack
                      )
                    }
                  : null;
              };

              const eventSummary = (eventName, event) => ({
                eventName,
                ts: new Date().toISOString(),
                action: event && event.action,
                trackKind: event && event.track && event.track.kind,
                participant: participantSummary(event && event.participant)
              });

              const remoteAudioId = (participant) =>
                participant.session_id || participant.user_id || participant.user_name || "unknown";

              const attachRemoteAudio = (participant, track) => {
                if (!participant || participant.local || !track || track.kind !== "audio") {
                  return;
                }
                const id = remoteAudioId(participant);
                let audioEl = window.__brainrhRemoteAudioElements[id];
                if (!audioEl) {
                  audioEl = document.createElement("audio");
                  audioEl.autoplay = true;
                  audioEl.playsInline = true;
                  audioEl.controls = false;
                  audioEl.dataset.brainrhRemoteAudio = id;
                  document.getElementById("remote-audio").appendChild(audioEl);
                  window.__brainrhRemoteAudioElements[id] = audioEl;
                }
                const currentTrack = audioEl.srcObject && audioEl.srcObject.getAudioTracks()[0];
                if (currentTrack !== track) {
                  audioEl.srcObject = new MediaStream([track]);
                }
                audioEl.muted = false;
                audioEl.volume = 1;
                const playPromise = audioEl.play();
                if (playPromise && typeof playPromise.catch === "function") {
                  playPromise.catch((error) => {
                    window.__brainrhDailyEvents.push({
                      eventName: "remote-audio-play-failed",
                      ts: new Date().toISOString(),
                      participant: participantSummary(participant),
                      error: error && error.message
                    });
                  });
                }
              };

              const syncVideoPlaceholder = () => {
                const container = document.getElementById("remote-media");
                if (!container) return;
                const hasVideo = Object.values(window.__brainrhRemoteVideoElements || {}).some(
                  (videoEl) => videoEl && videoEl.isConnected
                );
                const placeholder = container.querySelector(".placeholder");
                if (hasVideo && placeholder) {
                  placeholder.remove();
                } else if (!hasVideo && !placeholder) {
                  const nextPlaceholder = document.createElement("div");
                  nextPlaceholder.className = "placeholder";
                  nextPlaceholder.textContent = "En attente de la vidéo candidat";
                  container.appendChild(nextPlaceholder);
                }
              };

              const attachRemoteVideo = (participant, track) => {
                if (!participant || participant.local || !track || track.kind !== "video") {
                  return;
                }
                const id = remoteAudioId(participant);
                let videoEl = window.__brainrhRemoteVideoElements[id];
                if (!videoEl) {
                  videoEl = document.createElement("video");
                  videoEl.autoplay = true;
                  videoEl.playsInline = true;
                  videoEl.muted = true;
                  videoEl.controls = false;
                  videoEl.dataset.brainrhRemoteVideo = id;
                  document.getElementById("remote-media").appendChild(videoEl);
                  window.__brainrhRemoteVideoElements[id] = videoEl;
                }
                const currentTrack = videoEl.srcObject && videoEl.srcObject.getVideoTracks()[0];
                if (currentTrack !== track) {
                  videoEl.srcObject = new MediaStream([track]);
                }
                const playPromise = videoEl.play();
                if (playPromise && typeof playPromise.catch === "function") {
                  playPromise.catch((error) => {
                    window.__brainrhDailyEvents.push({
                      eventName: "remote-video-play-failed",
                      ts: new Date().toISOString(),
                      participant: participantSummary(participant),
                      error: error && error.message
                    });
                  });
                }
                syncVideoPlaceholder();
              };

              const removeRemoteAudio = (participant) => {
                if (!participant || participant.local) {
                  return;
                }
                const id = remoteAudioId(participant);
                const audioEl = window.__brainrhRemoteAudioElements[id];
                if (audioEl) {
                  audioEl.srcObject = null;
                  audioEl.remove();
                  delete window.__brainrhRemoteAudioElements[id];
                }
                const videoEl = window.__brainrhRemoteVideoElements[id];
                if (videoEl) {
                  videoEl.srcObject = null;
                  videoEl.remove();
                  delete window.__brainrhRemoteVideoElements[id];
                }
                syncVideoPlaceholder();
              };

              const refreshRemoteAudio = () => {
                Object.values(call.participants() || {}).forEach((participant) => {
                  if (!participant || participant.local) {
                    return;
                  }
                  const audioTrack = participant.tracks && participant.tracks.audio;
                  const track =
                    (audioTrack && (audioTrack.persistentTrack || audioTrack.track)) ||
                    participant.audioTrack;
                  attachRemoteAudio(participant, track);
                  const videoTrack = participant.tracks && participant.tracks.video;
                  const video =
                    (videoTrack && (videoTrack.persistentTrack || videoTrack.track)) ||
                    participant.videoTrack;
                  attachRemoteVideo(participant, video);
                });
                syncVideoPlaceholder();
              };

              [
                "joining-meeting",
                "joined-meeting",
                "participant-joined",
                "participant-updated",
                "participant-left",
                "track-started",
                "track-stopped",
                "left-meeting",
                "error"
              ].forEach((eventName) => {
                call.on(eventName, (event) => {
                  window.__brainrhDailyEvents.push(eventSummary(eventName, event));
                  if (eventName === "track-started") {
                    attachRemoteAudio(event && event.participant, event && event.track);
                    attachRemoteVideo(event && event.participant, event && event.track);
                  } else if (eventName === "track-stopped") {
                    refreshRemoteAudio();
                  } else if (eventName === "participant-left") {
                    removeRemoteAudio(event && event.participant);
                  } else if (
                    eventName === "participant-joined" ||
                    eventName === "participant-updated" ||
                    eventName === "joined-meeting"
                  ) {
                    refreshRemoteAudio();
                  }
                  console.log("daily-event", eventName);
                });
              });
              await call.join({
                url: roomUrl,
                token,
                userName: displayName,
                startVideoOff: true,
                startAudioOff: false
              });
              refreshRemoteAudio();
              return call.meetingState();
            }
            """,
            {"roomUrl": room_url, "token": token, "displayName": display_name},
        )
        if state != "joined-meeting":
            self._capture_debug("daily-sdk-join-not-confirmed")
            raise RuntimeError(f"Daily SDK join not confirmed: {state}")

    def _leave_daily_call_object(self) -> None:
        assert self._page is not None
        try:
            self._page.evaluate(
                """
                async () => {
                  const call = window.__brainrhDailyCall;
                  if (call) {
                    await call.leave();
                    await call.destroy();
                  }
                }
                """
            )
        except Exception:
            return

    def _snapshot(self) -> dict[str, object]:
        assert self._page is not None
        try:
            daily_snapshot = self._page.evaluate(
                """
                () => {
                  const call = window.__brainrhDailyCall;
                  if (!call) return null;
                  const aiDisplayName = window.__brainrhAiDisplayName || "BrainRH AI Interviewer";
                  const participants = Object.values(call.participants() || {});
                  const remote = participants.filter((participant) => !participant.local);
                  const candidates = remote.filter(
                    (participant) => (participant.user_name || "") !== aiDisplayName
                  );
                  const summarize = (participant) => {
                    const audioTrack = participant.tracks && participant.tracks.audio;
                    return {
                      local: participant.local,
                      user_name: participant.user_name || "",
                      audio: participant.audio,
                      video: participant.video,
                      audioState: audioTrack && audioTrack.state,
                      audioSubscribed: audioTrack && audioTrack.subscribed,
                      audioTrackReady: Boolean(
                        (audioTrack && (audioTrack.persistentTrack || audioTrack.track)) ||
                          participant.audioTrack
                      )
                    };
                  };
                  return {
                    state: call.meetingState(),
                    participantCount: participants.length,
                    candidateCount: candidates.length,
                    participantNames: participants.map((participant) => participant.user_name || ""),
                    participants: participants.map(summarize),
                    remoteAudioElementCount: Object.keys(window.__brainrhRemoteAudioElements || {}).length,
                    events: window.__brainrhDailyEvents || [],
                    text: document.body.innerText || ""
                  };
                }
                """
            )
            if daily_snapshot:
                return daily_snapshot
        except Exception:
            pass

        participant_keys: set[str] = set()
        texts: list[str] = []
        for frame_index, frame in enumerate(self._page.frames):
            try:
                frame_snapshot = frame.evaluate(
                    """
                    () => {
                      const nodes = [
                        ...document.querySelectorAll('[data-participant-id], [data-testid*="participant"], video')
                      ];
                      return {
                        participants: nodes.map((node, index) =>
                          node.getAttribute('data-participant-id') ||
                          node.getAttribute('data-testid') ||
                          node.getAttribute('aria-label') ||
                          String(index)
                        ),
                        text: document.body.innerText || ""
                      };
                    }
                    """
                )
            except Exception:
                continue
            texts.append(str(frame_snapshot.get("text") or ""))
            for participant in frame_snapshot.get("participants") or []:
                participant_keys.add(f"{frame_index}:{participant}")
        return {"participantCount": len(participant_keys), "text": "\n".join(texts)}

    def _start_idle_audio(self) -> None:
        if not self._audio_runtime or self._idle_audio_process:
            return
        self._idle_audio_process = subprocess.Popen(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-re",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r={self._audio_runtime.sample_rate}:cl=mono",
                "-f",
                "s16le",
                "-ac",
                "1",
                "-ar",
                str(self._audio_runtime.sample_rate),
                "-y",
                str(self._audio_runtime.mic_fifo_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop_idle_audio(self) -> None:
        if self._idle_audio_process and self._idle_audio_process.poll() is None:
            self._idle_audio_process.terminate()
            try:
                self._idle_audio_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._idle_audio_process.kill()
        self._idle_audio_process = None

    def _capture_debug(self, label: str) -> None:
        if not self._page:
            return
        try:
            self._debug_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            base_path = self._debug_dir / f"{timestamp}-{label}"
            self._page.screenshot(path=str(base_path.with_suffix(".png")), full_page=True)
            snapshot = self._snapshot()
            base_path.with_suffix(".json").write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._log(f"debug capture written: {base_path}")
        except Exception as exc:
            self._log(f"debug capture failed: {exc}")

    @staticmethod
    def _log(message: str) -> None:
        print(f"[cal-video-room] {message}", flush=True)
