"""Invitation envoyée au candidat pour un entretien mené par un recruteur.

Le message contient une version texte, une version HTML et un fichier .ics
(RFC 5545) que le candidat ajoute à son agenda. Les notes internes du recruteur
ne sont jamais incluses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ICS_PRODUCT_ID = "-//Brain Gen Technology//BRAIN HR Interview//FR"


@dataclass(frozen=True)
class InterviewInvitationDetails:
    appointment_id: str
    candidate_name: str
    candidate_email: str
    interviewer_name: str
    interviewer_email: str | None
    start_at: datetime
    end_at: datetime
    candidate_timezone: str
    meeting_format: str
    meeting_url: str | None
    meeting_location: str | None
    role_title: str | None
    language: str
    sequence: int = 0
    cancelled: bool = False
    interview_title: str | None = None


_COPY = {
    "fr": {
        "subject": "Invitation à un entretien",
        "subject_role": "Invitation à un entretien · {role}",
        "subject_cancelled": "Entretien annulé",
        "subject_cancelled_role": "Entretien annulé · {role}",
        "greeting": "Bonjour {name},",
        "intro": "{interviewer} vous propose un entretien{role_part}.",
        "role_part": " pour le poste de {role}",
        "intro_cancelled": "L'entretien prévu avec {interviewer}{role_part} est annulé.",
        "interview": "Entretien",
        "when": "Date et heure",
        "duration": "Durée",
        "minutes": "{minutes} min",
        "format": "Format",
        "formats": {"video": "Visioconférence", "phone": "Téléphone", "on_site": "Sur site"},
        "join": "Rejoindre la visio",
        "where": "Lieu",
        "phone_note": "{interviewer} vous appellera à l'heure prévue.",
        "calendar": "L'invitation jointe (.ics) ajoute l'entretien à votre agenda.",
        "calendar_cancelled": "La pièce jointe (.ics) retire l'entretien de votre agenda.",
        "reply": "Pour toute question, répondez simplement à cet e-mail.",
        "signoff": "Cordialement,",
        "via": "Envoyé via BRAIN HR",
        "summary": "Entretien · {candidate}",
        "summary_role": "Entretien · {role} · {candidate}",
        "timezone": "heure de {zone}",
    },
    "en": {
        "subject": "Interview invitation",
        "subject_role": "Interview invitation · {role}",
        "subject_cancelled": "Interview cancelled",
        "subject_cancelled_role": "Interview cancelled · {role}",
        "greeting": "Hello {name},",
        "intro": "{interviewer} invites you to an interview{role_part}.",
        "role_part": " for the {role} position",
        "intro_cancelled": "The interview planned with {interviewer}{role_part} has been cancelled.",
        "interview": "Interview",
        "when": "Date and time",
        "duration": "Duration",
        "minutes": "{minutes} min",
        "format": "Format",
        "formats": {"video": "Video call", "phone": "Phone call", "on_site": "On site"},
        "join": "Join the video call",
        "where": "Location",
        "phone_note": "{interviewer} will call you at the scheduled time.",
        "calendar": "The attached invitation (.ics) adds the interview to your calendar.",
        "calendar_cancelled": "The attachment (.ics) removes the interview from your calendar.",
        "reply": "If you have any questions, simply reply to this email.",
        "signoff": "Best regards,",
        "via": "Sent via BRAIN HR",
        "summary": "Interview · {candidate}",
        "summary_role": "Interview · {role} · {candidate}",
        "timezone": "{zone} time",
    },
}

_MONTHS = {
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
}
_WEEKDAYS = {
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}


def _language(value: str) -> str:
    return "en" if value == "en" else "fr"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _zone(name: str) -> tuple[ZoneInfo | timezone, str]:
    try:
        return ZoneInfo(name), name
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc, "UTC"


def format_interview_moment(details: InterviewInvitationDetails) -> str:
    """Date lisible dans le fuseau du candidat, sans dépendre de la locale système."""
    language = _language(details.language)
    zone, zone_name = _zone(details.candidate_timezone)
    start = _utc(details.start_at).astimezone(zone)
    end = _utc(details.end_at).astimezone(zone)
    weekday = _WEEKDAYS[language][start.weekday()]
    month = _MONTHS[language][start.month - 1]
    zone_label = _COPY[language]["timezone"].format(zone=zone_name)
    if language == "en":
        return f"{weekday}, {month} {start.day}, {start.year} · {start:%H:%M}–{end:%H:%M} ({zone_label})"
    return f"{weekday} {start.day} {month} {start.year} · {start:%H:%M}–{end:%H:%M} ({zone_label})"


def _role_values(details: InterviewInvitationDetails, copy: dict) -> tuple[str, str]:
    role = (details.role_title or "").strip()
    role_part = copy["role_part"].format(role=role) if role else ""
    return role, role_part


def render_interview_invitation(details: InterviewInvitationDetails) -> tuple[str, str, str]:
    """Retourne (sujet, texte, html)."""
    language = _language(details.language)
    copy = _COPY[language]
    role, role_part = _role_values(details, copy)
    if details.cancelled:
        subject = copy["subject_cancelled_role"].format(role=role) if role else copy["subject_cancelled"]
        intro = copy["intro_cancelled"].format(interviewer=details.interviewer_name, role_part=role_part)
    else:
        subject = copy["subject_role"].format(role=role) if role else copy["subject"]
        intro = copy["intro"].format(interviewer=details.interviewer_name, role_part=role_part)

    moment = format_interview_moment(details)
    minutes = max(1, round((_utc(details.end_at) - _utc(details.start_at)).total_seconds() / 60))
    rows: list[tuple[str, str, str | None]] = []
    if details.interview_title:
        rows.append((copy["interview"], details.interview_title, None))
    rows += [
        (copy["when"], moment, None),
        (copy["duration"], copy["minutes"].format(minutes=minutes), None),
        (copy["format"], copy["formats"].get(details.meeting_format, details.meeting_format), None),
    ]
    if details.meeting_location:
        rows.append((copy["where"], details.meeting_location, None))
    if details.meeting_url and not details.cancelled:
        rows.append((copy["join"], details.meeting_url, details.meeting_url))

    closing = copy["calendar_cancelled"] if details.cancelled else copy["calendar"]
    phone_note = (
        copy["phone_note"].format(interviewer=details.interviewer_name)
        if details.meeting_format == "phone" and not details.cancelled
        else None
    )

    text_lines = [copy["greeting"].format(name=details.candidate_name), "", intro, ""]
    text_lines.extend(f"{label} : {value}" if language == "fr" else f"{label}: {value}" for label, value, _ in rows)
    if phone_note:
        text_lines.extend(["", phone_note])
    text_lines.extend(["", closing, copy["reply"], "", copy["signoff"], details.interviewer_name, "", copy["via"]])
    text_body = "\n".join(text_lines) + "\n"

    esc = html.escape
    html_rows = "".join(
        '<tr><td style="padding:10px 16px;border-top:1px solid #e9ebed;font-size:12px;line-height:18px;'
        f'color:#69717d;width:34%;vertical-align:top;">{esc(label)}</td>'
        '<td style="padding:10px 16px;border-top:1px solid #e9ebed;font-size:14px;line-height:21px;'
        'color:#17191d;font-weight:700;word-break:break-word;overflow-wrap:anywhere;">'
        + (
            f'<a href="{esc(link, quote=True)}" style="color:#21657b;text-decoration:underline;">{esc(value)}</a>'
            if link
            else esc(value)
        )
        + "</td></tr>"
        for label, value, link in rows
    )
    phone_block = (
        f'<p style="margin:18px 0 0;font-size:15px;line-height:24px;color:#444b55;">{esc(phone_note)}</p>'
        if phone_note
        else ""
    )
    html_body = f"""<!doctype html>
<html lang="{language}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(subject)}</title></head>
<body style="margin:0;padding:0;background-color:#f2f3f4;color:#17191d;font-family:Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;background-color:#f2f3f4;">
    <tr><td align="center" style="padding:24px 12px;">
      <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:600px;background-color:#ffffff;border:1px solid #e1e4e7;border-radius:10px;">
        <tr><td style="padding:28px 24px;">
          <h1 style="margin:0 0 20px;font-size:22px;line-height:28px;font-weight:700;color:#17191d;">{esc(subject)}</h1>
          <p style="margin:0 0 12px;font-size:15px;line-height:24px;color:#17191d;">{esc(copy["greeting"].format(name=details.candidate_name))}</p>
          <p style="margin:0 0 20px;font-size:15px;line-height:24px;color:#444b55;">{esc(intro)}</p>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;background-color:#f6f7f8;border-radius:6px;">{html_rows}</table>{phone_block}
          <p style="margin:20px 0 6px;font-size:14px;line-height:22px;color:#444b55;">{esc(closing)}</p>
          <p style="margin:0 0 22px;font-size:14px;line-height:22px;color:#444b55;">{esc(copy["reply"])}</p>
          <p style="margin:0;font-size:14px;line-height:22px;color:#444b55;">{esc(copy["signoff"])}<br><strong style="color:#17191d;">{esc(details.interviewer_name)}</strong></p>
          <p style="margin:24px 0 0;padding-top:16px;border-top:1px solid #e9ebed;font-size:12px;line-height:18px;color:#69717d;">{esc(copy["via"])}</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    return subject, text_body, html_body


def _ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _ics_fold(line: str) -> str:
    """Replie une ligne à 75 octets (RFC 5545 §3.1) sans couper un caractère UTF-8."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts: list[str] = []
    current = ""
    limit = 75
    for char in line:
        if len((current + char).encode("utf-8")) > limit:
            parts.append(current)
            current = char
            limit = 74  # la ligne suivante commence par une espace
        else:
            current += char
    parts.append(current)
    return "\r\n ".join(parts)


def _ics_datetime(value: datetime) -> str:
    return _utc(value).strftime("%Y%m%dT%H%M%SZ")


def build_interview_ics(details: InterviewInvitationDetails, *, stamp: datetime) -> str:
    """METHOD:PUBLISH ajoute l'événement ; METHOD:CANCEL le retire (même UID)."""
    language = _language(details.language)
    copy = _COPY[language]
    role = (details.role_title or "").strip()
    summary = (
        copy["summary_role"].format(role=role, candidate=details.candidate_name)
        if role
        else copy["summary"].format(candidate=details.candidate_name)
    )
    description_lines = [
        f"{copy['format']} : {copy['formats'].get(details.meeting_format, details.meeting_format)}"
        if language == "fr"
        else f"{copy['format']}: {copy['formats'].get(details.meeting_format, details.meeting_format)}",
    ]
    if details.meeting_url:
        description_lines.append(details.meeting_url)
    if details.meeting_format == "phone":
        description_lines.append(copy["phone_note"].format(interviewer=details.interviewer_name))
    location = details.meeting_url or details.meeting_location or copy["formats"].get(details.meeting_format, "")

    method = "CANCEL" if details.cancelled else "PUBLISH"
    lines = [
        "BEGIN:VCALENDAR",
        f"PRODID:{ICS_PRODUCT_ID}",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:{details.appointment_id}@brainhr.interview",
        f"SEQUENCE:{details.sequence}",
        f"DTSTAMP:{_ics_datetime(stamp)}",
        f"DTSTART:{_ics_datetime(details.start_at)}",
        f"DTEND:{_ics_datetime(details.end_at)}",
        f"SUMMARY:{_ics_escape(summary)}",
        f"DESCRIPTION:{_ics_escape(chr(10).join(description_lines))}",
    ]
    if location:
        lines.append(f"LOCATION:{_ics_escape(location)}")
    if details.meeting_url:
        lines.append(f"URL:{details.meeting_url}")
    lines.append(f"STATUS:{'CANCELLED' if details.cancelled else 'CONFIRMED'}")
    lines.extend(["TRANSP:OPAQUE", "END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"
