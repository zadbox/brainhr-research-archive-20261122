from __future__ import annotations

import argparse
import os

from .backend import BrainRHBackendClient
from .cal_video_room import PlaywrightCalVideoRoomAdapter
from .config import get_settings
from .realtime_bridge import OpenAIRealtimeAudioBridge
from .worker import CalVideoInterviewWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="BrainRH Cal Video AI worker")
    parser.add_argument("appointment_id", nargs="?")
    args = parser.parse_args()
    appointment_id = args.appointment_id or os.getenv("BRAINRH_APPOINTMENT_ID")
    if not appointment_id:
        raise SystemExit("appointment_id requis ou BRAINRH_APPOINTMENT_ID manquant")

    settings = get_settings()
    if not settings.worker_event_secret:
        raise SystemExit("BRAINRH_WORKER_EVENT_SECRET manquant")
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY manquante")

    backend = BrainRHBackendClient(
        settings.backend_base_url,
        worker_secret=settings.worker_event_secret,
    )
    worker = CalVideoInterviewWorker(
        settings=settings,
        backend=backend,
        room=PlaywrightCalVideoRoomAdapter(settings),
        bridge=OpenAIRealtimeAudioBridge(settings=settings, backend=backend),
    )
    result = worker.run(appointment_id)
    print(f"[worker] appointment={result.appointment_id} status={result.status}")


if __name__ == "__main__":
    main()
