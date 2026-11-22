"""Réunions des entretiens menés par un recruteur.

Aujourd'hui, le recruteur saisit lui-même le lien de visio (Teams, Meet, Zoom…)
ou le lieu : BRAIN HR le conserve tel quel et envoie l'invitation au candidat.
Le futur connecteur Microsoft Teams implémentera ``HumanMeetingProvider`` pour
créer la réunion dans l'agenda Microsoft 365 ; Outlook enverra alors lui-même
l'invitation (``invitation_sent_by_provider``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from brainrh.models.interview_appointment import HumanMeetingFormat


MAX_MEETING_URL_LENGTH = 2048
MAX_MEETING_LOCATION_LENGTH = 500


@dataclass(frozen=True)
class HumanMeetingRequest:
    meeting_format: HumanMeetingFormat
    meeting_url: str | None
    meeting_location: str | None


@dataclass(frozen=True)
class HumanMeeting:
    provider: str
    meeting_format: str
    meeting_url: str | None
    meeting_location: str | None
    invitation_sent_by_provider: bool


class HumanMeetingProvider(Protocol):
    provider_id: str

    def prepare(self, request: HumanMeetingRequest) -> HumanMeeting: ...


def _clean_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    # Pas de caractères de contrôle : la valeur part dans un e-mail et un .ics.
    cleaned = " ".join("".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in value).split())
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise ValueError(f"Le lieu de l'entretien dépasse {max_length} caractères.")
    return cleaned


def validate_meeting_url(value: str | None) -> str | None:
    """Accepte uniquement une URL HTTPS absolue, sans identifiants intégrés."""
    if value is None or not value.strip():
        return None
    url = value.strip()
    if len(url) > MAX_MEETING_URL_LENGTH or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ValueError("Le lien de la réunion est invalide.")
    parsed = urlsplit(url)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Le lien de la réunion est invalide.") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "\\" in parsed.netloc
    ):
        raise ValueError("Le lien de la réunion doit être une adresse https:// valide.")
    return url


class ManualMeetingProvider:
    """Le recruteur fournit le lien ou le lieu ; BRAIN HR envoie l'invitation."""

    provider_id = "manual"

    def prepare(self, request: HumanMeetingRequest) -> HumanMeeting:
        meeting_format = HumanMeetingFormat(request.meeting_format)
        meeting_url = validate_meeting_url(request.meeting_url)
        meeting_location = _clean_text(request.meeting_location, max_length=MAX_MEETING_LOCATION_LENGTH)

        if meeting_format == HumanMeetingFormat.video:
            if not meeting_url:
                raise ValueError("Ajoutez le lien de la visio (Teams, Google Meet, Zoom…).")
            meeting_location = None
        elif meeting_format == HumanMeetingFormat.on_site:
            if not meeting_location:
                raise ValueError("Ajoutez l'adresse de l'entretien sur site.")
            meeting_url = None
        else:
            meeting_url = None

        return HumanMeeting(
            provider=self.provider_id,
            meeting_format=meeting_format.value,
            meeting_url=meeting_url,
            meeting_location=meeting_location,
            invitation_sent_by_provider=False,
        )


def get_human_meeting_provider() -> HumanMeetingProvider:
    return ManualMeetingProvider()
