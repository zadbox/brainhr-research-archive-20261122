"""Abstraction d'envoi des invitations utilisateur.

Le module ne journalise jamais le destinataire, l'URL d'activation ou le token.
La configuration SES est validee au moment de l'envoi et echoue ferme si un
prerequis manque.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
import re
from typing import Protocol

from brainrh.models.auth import UserRole
from brainrh.settings import (
    get_aws_region,
    get_email_provider,
    get_invitation_from_email,
    get_invitation_reply_to_email,
)
from brainrh.services.invitation_email_renderer import render_invitation_content


SAFE_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


class EmailConfigurationError(RuntimeError):
    pass


class EmailDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class InvitationEmail:
    recipient: str
    activation_url: str
    language: str
    role: UserRole
    requires_password: bool
    issued_at: datetime
    expires_at: datetime
    first_name: str | None = None
    last_name: str | None = None
    tenant_name: str | None = None
    trial_duration_days: int | None = None
    trial_started_at: datetime | None = None
    trial_expires_at: datetime | None = None
    trial_status: str | None = None


@dataclass(frozen=True)
class InterviewInvitationEmail:
    """Invitation d'entretien recruteur : texte, HTML et pièce jointe .ics."""

    recipient: str
    subject: str
    text_body: str
    html_body: str
    ics_content: str
    ics_method: str
    sender_display_name: str | None = None
    cc: tuple[str, ...] = ()
    reply_to: str | None = None


class EmailSender(Protocol):
    def send_invitation(self, message: InvitationEmail) -> str | None: ...

    def send_interview_invitation(self, message: InterviewInvitationEmail) -> str | None: ...


def validate_mailbox(value: str, *, setting_name: str) -> str:
    normalized = value.strip()
    parsed_name, parsed_address = parseaddr(normalized)
    if (
        not normalized
        or parsed_name
        or parsed_address != normalized
        or not SAFE_EMAIL_RE.fullmatch(normalized)
        or "\r" in normalized
        or "\n" in normalized
    ):
        raise EmailConfigurationError(f"{setting_name} doit contenir une adresse email simple valide.")
    return normalized


def _role_label(role: UserRole, language: str) -> str:
    labels = {
        "en": {
            UserRole.platform_admin: "Platform administrator",
            UserRole.client_admin: "Client administrator",
            UserRole.enterprise_admin: "Company administrator",
            UserRole.project_manager: "Project manager",
            UserRole.recruiter: "Recruiter",
            UserRole.viewer: "Viewer",
        },
        "fr": {
            UserRole.platform_admin: "Administrateur plateforme",
            UserRole.client_admin: "Administrateur client",
            UserRole.enterprise_admin: "Administrateur d'entreprise",
            UserRole.project_manager: "Chef de projet",
            UserRole.recruiter: "Recruteur",
            UserRole.viewer: "Lecteur",
        },
    }
    return labels[language][role]


SAFE_DISPLAY_NAME_RE = re.compile(r"[^\w .'’-]", re.UNICODE)


def _single_line(value: str, *, max_length: int) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())[:max_length]


def _display_name(value: str) -> str:
    """Nom d'expéditeur sans ponctuation d'adresse (``:``, ``@``, ``<``, ``;``…)."""
    return " ".join(SAFE_DISPLAY_NAME_RE.sub(" ", value).split())[:80]


def build_interview_invitation_mime(message: InterviewInvitationEmail, *, source: str) -> EmailMessage:
    """Construit le MIME multipart/mixed (alternative texte/HTML + .ics)."""
    if message.ics_method not in {"PUBLISH", "CANCEL"}:
        raise EmailConfigurationError("Methode calendrier non supportee.")
    recipient = validate_mailbox(message.recipient, setting_name="recipient")
    cc = tuple(
        dict.fromkeys(
            validate_mailbox(address, setting_name="cc")
            for address in message.cc
            if address and address.strip().lower() != recipient.lower()
        )
    )
    reply_to = validate_mailbox(message.reply_to, setting_name="reply_to") if message.reply_to else None
    display_name = "BRAIN HR"
    sender_name = _display_name(message.sender_display_name or "")
    if sender_name:
        display_name = f"{sender_name} via BRAIN HR"
    local_part, domain = source.rsplit("@", 1)

    mime = EmailMessage()
    mime["From"] = Address(display_name=display_name, username=local_part, domain=domain)
    mime["To"] = recipient
    if cc:
        mime["Cc"] = ", ".join(cc)
    if reply_to:
        mime["Reply-To"] = reply_to
    mime["Subject"] = _single_line(message.subject, max_length=200)
    mime["Message-ID"] = make_msgid(domain=source.rsplit("@", 1)[-1])
    mime.set_content(message.text_body)
    mime.add_alternative(message.html_body, subtype="html")
    mime.add_attachment(
        message.ics_content.encode("utf-8"),
        maintype="text",
        subtype="calendar",
        filename="invitation.ics" if message.ics_method == "PUBLISH" else "cancellation.ics",
        params={"method": message.ics_method, "charset": "UTF-8"},
    )
    return mime


def render_invitation_email(message: InvitationEmail) -> tuple[str, str, str]:
    language = "fr" if message.language == "fr" else "en"
    try:
        return render_invitation_content(
            activation_url=message.activation_url,
            language=language,
            first_name=message.first_name,
            last_name=message.last_name,
            role_label=_role_label(message.role, language),
            requires_password=message.requires_password,
            issued_at=message.issued_at,
            expires_at=message.expires_at,
            tenant_name=message.tenant_name,
            trial_duration_days=message.trial_duration_days,
            trial_started_at=message.trial_started_at,
            trial_expires_at=message.trial_expires_at,
            trial_status=message.trial_status,
        )
    except ValueError as exc:
        raise EmailConfigurationError(str(exc)) from exc


class SesEmailSender:
    def __init__(self) -> None:
        region = get_aws_region()
        source = get_invitation_from_email()
        if not region:
            raise EmailConfigurationError("AWS_REGION est requis pour envoyer une invitation.")
        if not source:
            raise EmailConfigurationError("BRAINRH_INVITATION_FROM_EMAIL est requis.")

        self._region = region
        self._source = validate_mailbox(source, setting_name="BRAINRH_INVITATION_FROM_EMAIL")
        reply_to = get_invitation_reply_to_email()
        self._reply_to = (
            validate_mailbox(reply_to, setting_name="BRAINRH_INVITATION_REPLY_TO_EMAIL")
            if reply_to
            else None
        )

    def send_invitation(self, message: InvitationEmail) -> str | None:
        recipient = validate_mailbox(message.recipient, setting_name="recipient")
        subject, text_body, html_body = render_invitation_email(message)

        try:
            import boto3
            from botocore.exceptions import BotoCoreError, ClientError
        except ImportError as exc:
            raise EmailConfigurationError("Le client AWS requis pour SES est indisponible.") from exc

        try:
            client = boto3.client("ses", region_name=self._region)
            request = {
                "Source": formataddr(("BRAIN HR", self._source)),
                "Destination": {"ToAddresses": [recipient]},
                "Message": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                },
            }
            if self._reply_to:
                request["ReplyToAddresses"] = [self._reply_to]
            response = client.send_email(**request)
        except (BotoCoreError, ClientError) as exc:
            raise EmailDeliveryError("AWS SES n'a pas accepte l'invitation.") from exc

        message_id = response.get("MessageId")
        return str(message_id) if message_id else None

    def send_interview_invitation(self, message: InterviewInvitationEmail) -> str | None:
        mime = build_interview_invitation_mime(message, source=self._source)
        if not message.reply_to and self._reply_to:
            mime["Reply-To"] = self._reply_to
        destinations = [mime["To"], *[address.strip() for address in (mime["Cc"] or "").split(",") if address.strip()]]

        try:
            import boto3
            from botocore.exceptions import BotoCoreError, ClientError
        except ImportError as exc:
            raise EmailConfigurationError("Le client AWS requis pour SES est indisponible.") from exc

        try:
            client = boto3.client("ses", region_name=self._region)
            response = client.send_raw_email(
                Source=self._source,
                Destinations=destinations,
                RawMessage={"Data": mime.as_bytes()},
            )
        except (BotoCoreError, ClientError) as exc:
            raise EmailDeliveryError("AWS SES n'a pas accepte l'invitation d'entretien.") from exc

        message_id = response.get("MessageId")
        return str(message_id) if message_id else None


def get_email_sender() -> EmailSender:
    provider = get_email_provider()
    if provider == "ses":
        return SesEmailSender()
    if provider == "disabled":
        raise EmailConfigurationError("L'envoi d'invitations est desactive.")
    raise EmailConfigurationError("BRAINRH_EMAIL_PROVIDER doit valoir disabled ou ses.")
