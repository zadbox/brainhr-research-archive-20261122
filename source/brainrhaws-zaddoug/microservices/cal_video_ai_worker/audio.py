from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
import subprocess
import threading
import time

from .config import WorkerSettings


@dataclass(frozen=True)
class AudioRuntime:
    sample_rate: int
    chunk_bytes: int
    capture_device: str
    mic_fifo_path: Path


class PulseAudioController:
    def __init__(self, settings: WorkerSettings, *, runner=subprocess.run, process_launcher=subprocess.Popen):
        self.settings = settings
        self.runner = runner
        self.process_launcher = process_launcher
        self.mic_fifo_path = Path(os.getenv("CAL_VIDEO_MIC_FIFO", "/tmp/brainrh_ai_mic.raw"))

    def prepare(self) -> AudioRuntime:
        self._ensure_pulseaudio()
        self._ensure_null_sink()
        self._ensure_pipe_source()
        self._run(["pactl", "set-default-sink", self.settings.pulse_sink_name])
        self._run(["pactl", "set-default-source", self.settings.pulse_source_name])

        chunk_bytes = int(self.settings.audio_sample_rate * 2 * self.settings.audio_chunk_ms / 1000)
        return AudioRuntime(
            sample_rate=self.settings.audio_sample_rate,
            chunk_bytes=max(chunk_bytes, 480),
            capture_device=self.settings.capture_device,
            mic_fifo_path=self.mic_fifo_path,
        )

    def _ensure_pulseaudio(self) -> None:
        self._run(["pulseaudio", "--start"], check=False)
        if self._pactl_is_available():
            return

        self.process_launcher(
            ["pulseaudio", "--exit-idle-time=-1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(20):
            if self._pactl_is_available():
                return
            time.sleep(0.25)
        raise RuntimeError("PulseAudio is not reachable via pactl after startup")

    def _ensure_null_sink(self) -> None:
        if self._has_named_device("sinks", self.settings.pulse_sink_name):
            return
        self._run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                f"sink_name={self.settings.pulse_sink_name}",
                "sink_properties=device.description=BrainRH-CalVideo",
            ]
        )
        if not self._has_named_device("sinks", self.settings.pulse_sink_name):
            raise RuntimeError(f"PulseAudio sink {self.settings.pulse_sink_name!r} was not created")

    def _ensure_pipe_source(self) -> None:
        if self._has_named_device("sources", self.settings.pulse_source_name):
            return
        if self.mic_fifo_path.exists():
            self.mic_fifo_path.unlink()
        self._run(
            [
                "pactl",
                "load-module",
                "module-pipe-source",
                f"source_name={self.settings.pulse_source_name}",
                f"file={self.mic_fifo_path}",
                "format=s16le",
                f"rate={self.settings.audio_sample_rate}",
                "channels=1",
            ]
        )
        if not self._has_named_device("sources", self.settings.pulse_source_name):
            raise RuntimeError(f"PulseAudio source {self.settings.pulse_source_name!r} was not created")

    def _pactl_is_available(self) -> bool:
        try:
            result = self._run(["pactl", "info"], check=False)
        except FileNotFoundError as exc:
            raise RuntimeError("pactl is required by the Cal Video AI worker") from exc
        return result.returncode == 0

    def _has_named_device(self, device_kind: str, name: str) -> bool:
        result = self._run(["pactl", "list", "short", device_kind], stdout=subprocess.PIPE, text=True)
        return any(_short_list_name(line) == name for line in result.stdout.splitlines())

    def _run(self, args, *, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=False):
        try:
            return self.runner(args, check=check, stdout=stdout, stderr=stderr, text=text)
        except FileNotFoundError as exc:
            raise RuntimeError(f"{args[0]} is required by the Cal Video AI worker") from exc


def _short_list_name(line: str) -> str | None:
    parts = line.split("\t")
    if len(parts) < 2:
        return None
    return parts[1]


class FFmpegAudioPipes:
    def __init__(self, runtime: AudioRuntime, *, popen=subprocess.Popen):
        self.runtime = runtime
        self.popen = popen
        self.capture_process = None
        self.playback_process = None

    def start_capture(self):
        if shutil.which("parec"):
            command = [
                "parec",
                "--record",
                "--raw",
                f"--device={self.runtime.capture_device}",
                f"--rate={self.runtime.sample_rate}",
                "--format=s16le",
                "--channels=1",
            ]
        else:
            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "pulse",
                "-i",
                self.runtime.capture_device,
                "-ac",
                "1",
                "-ar",
                str(self.runtime.sample_rate),
                "-f",
                "s16le",
                "pipe:1",
            ]
        self.capture_process = self.popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return self.capture_process.stdout

    def start_playback(self):
        self.playback_process = ContinuousFifoAudioWriter(
            fifo_path=self.runtime.mic_fifo_path,
            sample_rate=self.runtime.sample_rate,
        )
        self.playback_process.start()
        return self.playback_process

    def stop(self) -> None:
        if self.capture_process and self.capture_process.poll() is None:
            process = self.capture_process
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if self.playback_process:
            stop = getattr(self.playback_process, "stop", None)
            if callable(stop):
                stop()
            elif self.playback_process.poll() is None:
                process = self.playback_process
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()


class FFmpegCallRecorder:
    def __init__(self, settings: WorkerSettings, runtime: AudioRuntime, *, popen=subprocess.Popen):
        self.settings = settings
        self.runtime = runtime
        self.popen = popen
        self.process = None
        self.output_path: Path | None = None
        self.host_path: Path | None = None
        self.log_path: Path | None = None
        self._log_handle = None
        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None
        self._error: str | None = None

    def start(self, appointment_id: str) -> None:
        if not self.settings.local_recording_enabled:
            return
        display = os.getenv("DISPLAY")
        if not display:
            self._error = "DISPLAY is not set; local video recording skipped"
            return
        if not shutil.which("ffmpeg"):
            self._error = "ffmpeg is not available; local video recording skipped"
            return

        recording_dir = Path(self.settings.local_recording_dir)
        recording_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"{appointment_id}-{stamp}.mp4"
        self.output_path = recording_dir / filename
        self.log_path = recording_dir / f"{appointment_id}-{stamp}.ffmpeg.log"
        if self.settings.local_recording_host_dir:
            self.host_path = Path(self.settings.local_recording_host_dir) / filename

        output_width, output_height = _parse_video_size(self.settings.local_recording_video_size)
        video_filter = (
            f"[0:v]fps={self.settings.local_recording_framerate},"
            f"scale={output_width}:{output_height}:force_original_aspect_ratio=decrease,"
            f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            "setsar=1[v];"
            "[1:a][2:a]amix=inputs=2:duration=longest:normalize=0[a]"
        )

        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-thread_queue_size",
            "512",
            "-f",
            "x11grab",
            "-draw_mouse",
            "0",
            "-video_size",
            self.settings.local_recording_capture_size,
            "-framerate",
            str(self.settings.local_recording_framerate),
            "-i",
            display,
            "-thread_queue_size",
            "512",
            "-f",
            "pulse",
            "-i",
            self.runtime.capture_device,
            "-thread_queue_size",
            "512",
            "-f",
            "pulse",
            "-i",
            self.settings.pulse_source_name,
            "-filter_complex",
            video_filter,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(self.output_path),
        ]
        self._log_handle = self.log_path.open("ab") if self.log_path else subprocess.DEVNULL
        self.process = self.popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=self._log_handle,
            start_new_session=True,
        )
        self._started_at = datetime.now(timezone.utc)

    def stop(self) -> None:
        self._stopped_at = datetime.now(timezone.utc)
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self._log_handle and self._log_handle is not subprocess.DEVNULL:
            self._log_handle.close()
            self._log_handle = None

    def artifact(self) -> dict[str, object] | None:
        if not self.settings.local_recording_enabled and not self.output_path:
            return None

        size_bytes = 0
        if self.output_path and self.output_path.exists():
            size_bytes = self.output_path.stat().st_size

        returncode = self.process.poll() if self.process else None
        status = "recording"
        if size_bytes > 0:
            status = "completed"
        elif self._error or returncode is not None or self._stopped_at is not None:
            status = "failed"
        return {
            "id": self.output_path.stem if self.output_path else None,
            "provider": "brainrh_worker_local",
            "type": "call_recording",
            "status": status,
            "path": str(self.host_path or self.output_path) if (self.host_path or self.output_path) else None,
            "container_path": str(self.output_path) if self.output_path else None,
            "log_path": str(self.log_path) if self.log_path else None,
            "capture_size": self.settings.local_recording_capture_size,
            "video_size": self.settings.local_recording_video_size,
            "resolution": self.settings.local_recording_resolution,
            "framerate": self.settings.local_recording_framerate,
            "size_bytes": size_bytes,
            "returncode": returncode,
            "started_at": self._iso_z(self._started_at),
            "stopped_at": self._iso_z(self._stopped_at),
            "error": self._error,
        }

    @staticmethod
    def _iso_z(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_video_size(value: str) -> tuple[int, int]:
    try:
        width_raw, height_raw = value.lower().split("x", 1)
        width = int(width_raw)
        height = int(height_raw)
    except (AttributeError, ValueError):
        return 640, 360
    if width <= 0 or height <= 0:
        return 640, 360
    return width, height


class ContinuousFifoAudioWriter:
    """Continuously feeds PulseAudio pipe-source to avoid virtual mic underruns."""

    def __init__(
        self,
        *,
        fifo_path: Path,
        sample_rate: int,
        frame_ms: int = 20,
        prebuffer_ms: int = 240,
        max_buffer_seconds: float = 45.0,
    ) -> None:
        self.fifo_path = Path(fifo_path)
        self.sample_rate = sample_rate
        self.frame_bytes = max(int(sample_rate * 2 * frame_ms / 1000), 2)
        if self.frame_bytes % 2:
            self.frame_bytes += 1
        self.frame_seconds = frame_ms / 1000
        self.prebuffer_bytes = max(int(sample_rate * 2 * prebuffer_ms / 1000), self.frame_bytes)
        self.max_buffer_bytes = int(sample_rate * 2 * max_buffer_seconds)
        self._buffer = bytearray()
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._write_error: BaseException | None = None
        self._playing_buffered_audio = False
        self._force_play_buffered_audio = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="brainrh-fifo-audio-writer", daemon=True)
        self._thread.start()

    def write(self, data: bytes) -> int:
        if self._write_error:
            raise BrokenPipeError(str(self._write_error))
        if not data:
            return 0
        written = 0
        with self._condition:
            while written < len(data):
                while (
                    len(self._buffer) >= self.max_buffer_bytes
                    and not self._stop_event.is_set()
                    and not self._write_error
                ):
                    self._condition.wait(timeout=self.frame_seconds)
                if self._write_error:
                    raise BrokenPipeError(str(self._write_error))
                if self._stop_event.is_set():
                    break
                available_bytes = self.max_buffer_bytes - len(self._buffer)
                if available_bytes <= 0:
                    continue
                chunk = data[written : written + available_bytes]
                self._buffer.extend(chunk)
                written += len(chunk)
                self._condition.notify_all()
        return written

    def flush(self) -> None:
        return None

    def finish_segment(self) -> None:
        with self._condition:
            self._force_play_buffered_audio = True
            self._condition.notify_all()

    def clear(self) -> None:
        with self._condition:
            self._buffer.clear()
            self._playing_buffered_audio = False
            self._force_play_buffered_audio = False
            self._condition.notify_all()

    def pending_bytes(self) -> int:
        with self._condition:
            return len(self._buffer)

    def wait_until_drained(self, *, timeout: float) -> bool:
        deadline = time.monotonic() + max(timeout, 0)
        with self._condition:
            self._force_play_buffered_audio = True
            self._condition.notify_all()
            while self._buffer and not self._stop_event.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=min(remaining, self.frame_seconds))
            return not self._buffer

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        try:
            with self.fifo_path.open("wb", buffering=0) as fifo:
                next_write_at = time.monotonic()
                while not self._stop_event.is_set():
                    fifo.write(self._next_frame())
                    next_write_at += self.frame_seconds
                    sleep_for = next_write_at - time.monotonic()
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                    else:
                        next_write_at = time.monotonic()
        except BaseException as exc:
            self._write_error = exc

    def _next_frame(self) -> bytes:
        with self._condition:
            if not self._playing_buffered_audio:
                if len(self._buffer) < self.prebuffer_bytes and not self._force_play_buffered_audio:
                    return b"\x00" * self.frame_bytes
                self._playing_buffered_audio = True
                self._force_play_buffered_audio = False

            if len(self._buffer) >= self.frame_bytes:
                frame = bytes(self._buffer[: self.frame_bytes])
                del self._buffer[: self.frame_bytes]
                self._condition.notify_all()
                return frame
            if self._buffer:
                frame = bytes(self._buffer)
                self._buffer.clear()
                self._playing_buffered_audio = False
                self._force_play_buffered_audio = False
                self._condition.notify_all()
                return frame + (b"\x00" * (self.frame_bytes - len(frame)))
            self._playing_buffered_audio = False
            self._force_play_buffered_audio = False
            self._condition.notify_all()
        return b"\x00" * self.frame_bytes
