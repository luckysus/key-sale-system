import smtplib
from email.message import EmailMessage
from typing import Any


def send_smtp(settings: dict[str, Any], subject: str, body: str) -> None:
    host = str(settings.get("host") or "").strip()
    port = int(settings.get("port") or 0)
    from_email = str(settings.get("from_email") or settings.get("username") or "").strip()
    to_email = str(settings.get("to_email") or "").strip()
    if not host or not port or not from_email or not to_email:
        raise ValueError("SMTP 配置不完整")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = to_email
    message.set_content(body)

    client_cls = smtplib.SMTP_SSL if settings.get("use_ssl") else smtplib.SMTP
    with client_cls(host, port, timeout=15) as server:
        if settings.get("use_tls") and not settings.get("use_ssl"):
            server.starttls()
        username = str(settings.get("username") or "").strip()
        password = str(settings.get("password") or "")
        if username:
            server.login(username, password)
        server.send_message(message)
