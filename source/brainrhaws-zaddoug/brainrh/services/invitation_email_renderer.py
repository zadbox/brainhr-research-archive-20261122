"""Accessible, bilingual HTML and plain-text rendering for invitations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
from urllib.parse import SplitResult, urlsplit


SAFE_URL_SCHEMES = frozenset({"http", "https"})
INVITATION_ASSET_PATH = "/api/v1/auth/invitations/assets"


def _utc(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} doit etre une date valide.")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _validated_activation_url(value: str) -> tuple[str, SplitResult]:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("L'URL d'activation est invalide.")

    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("L'URL d'activation est invalide.") from exc
    if (
        parsed.scheme.lower() not in SAFE_URL_SCHEMES
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "\\" in parsed.netloc
    ):
        raise ValueError("L'URL d'activation doit etre une URL HTTP(S) absolue sure.")

    try:
        hostname = parsed.hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("L'URL d'activation est invalide.") from exc
    if ":" in hostname:
        hostname = f"[{hostname}]"
    authority = f"{hostname}:{port}" if port is not None else hostname
    normalized = SplitResult(
        parsed.scheme.lower(),
        authority,
        parsed.path,
        parsed.query,
        parsed.fragment,
    )
    return normalized.geturl(), normalized


def _asset_url(parsed_activation_url: SplitResult, filename: str) -> str:
    return (
        f"{parsed_activation_url.scheme}://{parsed_activation_url.netloc}"
        f"{INVITATION_ASSET_PATH}/{filename}"
    )


def _deadline_text(expires_at: datetime, language: str) -> str:
    if language == "fr":
        months = (
            "janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre", "décembre",
        )
        return (
            f"{expires_at.day:02d} {months[expires_at.month - 1]} {expires_at.year} "
            f"à {expires_at:%H:%M} UTC"
        )
    months = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    return (
        f"{months[expires_at.month - 1]} {expires_at.day}, {expires_at.year} "
        f"at {expires_at:%H:%M} UTC"
    )


def render_invitation_content(
    *,
    activation_url: str,
    language: str,
    role_label: str,
    requires_password: bool,
    issued_at: datetime,
    expires_at: datetime,
    first_name: str | None = None,
    last_name: str | None = None,
    tenant_name: str | None = None,
    trial_duration_days: int | None = None,
    trial_started_at: datetime | None = None,
    trial_expires_at: datetime | None = None,
    trial_status: str | None = None,
) -> tuple[str, str, str]:
    """Render an invitation without leaking activation data into asset URLs."""

    activation_url, parsed_activation_url = _validated_activation_url(activation_url)
    issued_at = _utc(issued_at, field_name="issued_at")
    expires_at = _utc(expires_at, field_name="expires_at")
    if expires_at <= issued_at:
        raise ValueError("expires_at doit etre posterieur a issued_at.")

    five_day_validity = expires_at - issued_at == timedelta(days=5)
    deadline = _deadline_text(expires_at, language)
    animated_logo_url = _asset_url(parsed_activation_url, "brain-b-v1.gif")
    static_logo_url = _asset_url(parsed_activation_url, "brain-b-v1.png")
    recipient_name = " ".join(part for part in (first_name, last_name) if part)
    if trial_duration_days is not None and not 1 <= trial_duration_days <= 365:
        raise ValueError("trial_duration_days doit etre compris entre 1 et 365.")
    trial_started_at = _utc(trial_started_at, field_name="trial_started_at") if trial_started_at else None
    trial_expires_at = _utc(trial_expires_at, field_name="trial_expires_at") if trial_expires_at else None

    if language == "fr":
        subject = "Votre invitation Brain HR"
        title = "Votre invitation à Brain HR"
        preheader = "Rejoignez votre espace de travail Brain HR."
        greeting = f"Bienvenue {recipient_name}," if recipient_name else "Bienvenue,"
        introduction = (
            f"Vous êtes invité à rejoindre l’espace client {tenant_name} sur Brain HR."
            if tenant_name
            else "Vous êtes invité à rejoindre un espace de travail sur Brain HR."
        )
        role_heading = "RÔLE ATTRIBUÉ"
        password_note = (
            "Pour finaliser votre accès, vous définirez votre mot de passe sur la page sécurisée."
            if requires_password
            else "Votre mot de passe actuel reste inchangé, sauf si vous choisissez d’en définir un nouveau."
        )
        action = "Rejoindre mon espace"
        security_heading = "Une invitation personnelle, à usage unique."
        validity = f"Ce lien expire le {deadline}."
        if five_day_validity:
            validity += " Sa durée de validité est de 5 jours."
        trial_note = ""
        if trial_duration_days is not None:
            if trial_status == "pending":
                trial_note = (
                    f"L’essai client de {trial_duration_days} jours commencera lors de la première "
                    "activation d’un administrateur client."
                )
            elif trial_expires_at is not None:
                trial_deadline = _deadline_text(trial_expires_at, language)
                trial_note = (
                    f"L’essai client {'a expiré' if trial_status == 'expired' else 'se termine'} "
                    f"le {trial_deadline}."
                )
        ignore_note = "Si vous n’attendiez pas cette invitation, vous pouvez ignorer cet e-mail."
        forward_note = "Ne transmettez pas ce lien personnel à une autre personne."
        fallback_note = "Si le bouton ne fonctionne pas, utilisez ce lien :"
        signoff = "Au plaisir de vous retrouver sur Brain HR,"
        team = "L’équipe Brain HR"
        text_body = (
            f"{title}\n\n{greeting}\n{introduction}\n\n"
            f"Rôle attribué : {role_label}\n{password_note}\n\n"
            f"{trial_note + chr(10) + chr(10) if trial_note else ''}"
            f"{action} : {activation_url}\n\n{security_heading}\n{validity}\n"
            f"{forward_note}\n{ignore_note}\n\n{signoff}\n{team}\nBrain Gen Technology"
        )
    else:
        subject = "Your Brain HR invitation"
        title = "Your invitation to Brain HR"
        preheader = "Join your Brain HR workspace."
        greeting = f"Welcome {recipient_name}," if recipient_name else "Welcome,"
        introduction = (
            f"You have been invited to join the {tenant_name} client workspace on Brain HR."
            if tenant_name
            else "You have been invited to join a workspace on Brain HR."
        )
        role_heading = "ASSIGNED ROLE"
        password_note = (
            "To finish setting up your access, you will create your password on the secure page."
            if requires_password
            else "Your current password remains unchanged unless you choose to set a new one."
        )
        action = "Join my workspace"
        security_heading = "A personal, single-use invitation."
        validity = f"This link expires on {deadline}."
        if five_day_validity:
            validity += " It is valid for 5 days."
        trial_note = ""
        if trial_duration_days is not None:
            if trial_status == "pending":
                trial_note = (
                    f"The {trial_duration_days}-day client trial starts when the first client "
                    "administrator activates their account."
                )
            elif trial_expires_at is not None:
                trial_deadline = _deadline_text(trial_expires_at, language)
                trial_note = (
                    f"The client trial {'expired' if trial_status == 'expired' else 'ends'} "
                    f"on {trial_deadline}."
                )
        ignore_note = "If you were not expecting this invitation, you can ignore this email."
        forward_note = "Do not forward this personal link to anyone else."
        fallback_note = "If the button does not work, use this link:"
        signoff = "We look forward to welcoming you to Brain HR,"
        team = "The Brain HR team"
        text_body = (
            f"{title}\n\n{greeting}\n{introduction}\n\n"
            f"Assigned role: {role_label}\n{password_note}\n\n"
            f"{trial_note + chr(10) + chr(10) if trial_note else ''}"
            f"{action}: {activation_url}\n\n{security_heading}\n{validity}\n"
            f"{forward_note}\n{ignore_note}\n\n{signoff}\n{team}\nBrain Gen Technology"
        )

    escaped = {
        "action": html.escape(action),
        "animated_logo_url": html.escape(animated_logo_url, quote=True),
        "deadline_and_validity": html.escape(validity),
        "greeting": html.escape(greeting),
        "ignore_note": html.escape(ignore_note),
        "forward_note": html.escape(forward_note),
        "fallback_note": html.escape(fallback_note),
        "introduction": html.escape(introduction),
        "password_note": html.escape(password_note),
        "preheader": html.escape(preheader),
        "role_heading": html.escape(role_heading),
        "role_label": html.escape(role_label),
        "safe_url": html.escape(activation_url, quote=True),
        "security_heading": html.escape(security_heading),
        "signoff": html.escape(signoff),
        "static_logo_url": html.escape(static_logo_url, quote=True),
        "team": html.escape(team),
        "title": html.escape(title),
        "trial_note": html.escape(trial_note),
        "trial_note_block": (
            f'<p style="margin:18px 0 0;font-size:14px;line-height:22px;color:#444b55;">'
            f'{html.escape(trial_note)}</p>'
            if trial_note
            else ""
        ),
    }
    html_body = """<!doctype html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <style>
    .brain-b-static {{ display:none !important; }}
    @media (prefers-reduced-motion: reduce) {{
      .brain-b-motion {{ display:none !important; }}
      .brain-b-static {{ display:block !important; }}
    }}
    @media screen and (max-width: 620px) {{
      .email-shell {{ padding:12px 8px !important; }}
      .email-content {{ padding:24px 18px 22px !important; }}
      .email-header {{ padding:16px 18px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f2f3f4;color:#17191d;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{preheader}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;background-color:#f2f3f4;">
    <tr><td class="email-shell" align="center" style="padding:24px 12px;">
      <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:600px;">
        <tr><td style="background-color:#ffffff;border:1px solid #e1e4e7;border-radius:10px;overflow:hidden;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
            <tr><td class="email-header" style="padding:18px 24px;border-bottom:1px solid #e9ebed;">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr>
                <td width="60" height="60" valign="middle" align="center" style="width:60px;height:60px;background-color:#000000;border-radius:4px;">
                  <img class="brain-b-motion" src="{animated_logo_url}" width="60" height="60" alt="B — Brain HR" style="display:block;width:60px;height:60px;border:0;border-radius:4px;background-color:#000000;color:#ffffff;font-size:18px;font-weight:700;line-height:60px;text-align:center;">
                  <img class="brain-b-static" src="{static_logo_url}" width="60" height="60" alt="B — Brain HR" style="display:none;width:60px;height:60px;border:0;border-radius:4px;background-color:#000000;color:#ffffff;font-size:18px;font-weight:700;line-height:60px;text-align:center;">
                </td>
                <td valign="middle" style="padding-left:14px;"><p style="margin:0 0 3px;font-size:20px;line-height:24px;font-weight:700;color:#17191d;">Brain HR</p><p style="margin:0;font-size:12px;line-height:17px;color:#6c737d;">Brain Gen Technology</p></td>
              </tr></table>
            </td></tr>
            <tr><td class="email-content" style="padding:30px 24px 26px;">
              <h1 style="margin:0 0 24px;font-size:26px;line-height:32px;font-weight:700;color:#17191d;">{title}</h1>
              <p style="margin:0 0 14px;font-size:15px;line-height:24px;color:#17191d;">{greeting}</p>
              <p style="margin:0 0 22px;font-size:15px;line-height:24px;color:#444b55;">{introduction}</p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;background-color:#f6f7f8;border-radius:6px;"><tr><td style="padding:15px 16px 4px;font-size:11px;line-height:17px;letter-spacing:.8px;color:#69717d;">{role_heading}</td></tr><tr><td style="padding:0 16px 15px;font-size:14px;line-height:21px;font-weight:700;color:#17191d;">{role_label}</td></tr></table>
              <p style="margin:22px 0 18px;font-size:15px;line-height:24px;color:#444b55;">{password_note}</p>{trial_note_block}
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;"><tr><td style="border:1.5px solid #21657b;border-radius:4px;background-color:#ffffff;"><a href="{safe_url}" style="display:block;padding:13px 16px;color:#21657b;text-decoration:none;font-size:15px;line-height:20px;font-weight:700;">{action}<span aria-hidden="true" style="float:right;font-size:19px;font-weight:400;">→</span></a></td></tr></table>
              <p style="margin:10px 0 0;font-size:11px;line-height:18px;color:#69717d;word-break:break-all;overflow-wrap:anywhere;">{fallback_note}<br><a href="{safe_url}" style="color:#21657b;text-decoration:underline;word-break:break-all;">{safe_url}</a></p>
              <p style="margin:22px 0 6px;font-size:14px;line-height:22px;font-weight:700;color:#17191d;">{security_heading}</p>
              <p style="margin:0 0 8px;font-size:14px;line-height:22px;color:#59616c;">{deadline_and_validity}</p>
              <p style="margin:0 0 22px;font-size:12px;line-height:19px;color:#69717d;">{forward_note}<br>{ignore_note}</p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;border-top:1px solid #e9ebed;"><tr><td style="padding-top:22px;"><p style="margin:0 0 14px;font-size:14px;line-height:22px;color:#444b55;">{signoff}</p><table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr><td width="28" valign="middle" align="center"><img src="{static_logo_url}" width="28" height="28" alt="B — Brain HR" style="display:block;width:28px;height:28px;border:0;border-radius:3px;background-color:#000000;color:#ffffff;font-size:12px;font-weight:700;line-height:28px;text-align:center;"></td><td valign="middle" style="padding-left:11px;"><p style="margin:0 0 2px;font-size:14px;line-height:19px;font-weight:700;color:#17191d;">{team}</p><p style="margin:0;font-size:12px;line-height:17px;color:#69717d;">Brain Gen Technology</p></td></tr></table></td></tr></table>
            </td></tr>
          </table>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>""".format(language=language, **escaped)
    return subject, text_body, html_body
