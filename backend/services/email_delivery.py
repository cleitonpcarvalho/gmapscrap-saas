import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy.orm import Session

from backend.models import SmtpConfig
from backend.services.crypto import decrypt_secret, encrypt_secret


def get_smtp_config(db: Session) -> SmtpConfig | None:
    return db.get(SmtpConfig, 1)


def get_or_create_smtp_config(db: Session) -> SmtpConfig:
    config = get_smtp_config(db)
    if config:
        return config

    config = SmtpConfig(id=1, host="smtp.zoho.com", port=465, use_ssl=True, use_tls=False)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_smtp_config(db: Session, data: dict) -> SmtpConfig:
    config = get_or_create_smtp_config(db)
    password = data.pop("password", None)

    for field, value in data.items():
        if hasattr(config, field):
            setattr(config, field, value.strip() if isinstance(value, str) else value)

    if password:
        config.password_encrypted = encrypt_secret(password)

    db.commit()
    db.refresh(config)
    return config


def _smtp_password(config: SmtpConfig) -> str:
    return decrypt_secret(config.password_encrypted)


def send_email(config: SmtpConfig, to_email: str, subject: str, html: str, text: str = "") -> None:
    password = _smtp_password(config)
    if not config.username or not password:
        raise RuntimeError("SMTP sem usuário ou senha.")

    from_email = config.from_email or config.username
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((config.from_name, from_email)) if config.from_name else from_email
    message["To"] = to_email

    if config.reply_to:
        message["Reply-To"] = config.reply_to

    message.set_content(text or "Abra este e-mail em um cliente com HTML.")
    message.add_alternative(html, subtype="html")

    try:
        if config.use_ssl:
            with smtplib.SMTP_SSL(config.host, config.port, timeout=30) as smtp:
                smtp.login(config.username, password)
                smtp.send_message(message)
            return

        with smtplib.SMTP(config.host, config.port, timeout=30) as smtp:
            if config.use_tls:
                smtp.starttls()
            smtp.login(config.username, password)
            smtp.send_message(message)
    except smtplib.SMTPResponseException as exc:
        detail = exc.smtp_error.decode("utf-8", errors="ignore") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
        if exc.smtp_code == 553:
            raise RuntimeError(
                "Zoho recusou o remetente. Use no campo From e-mail o mesmo endereço do usuário SMTP "
                "ou um alias autorizado nessa conta."
            ) from None
        raise RuntimeError(f"SMTP {exc.smtp_code}: {detail}") from None


def send_test_email(config: SmtpConfig, to_email: str) -> None:
    html = """
    <p>Teste SMTP do GmapScrap.</p>
    <p>Se voce recebeu este e-mail, a configuracao esta funcionando.</p>
    """
    send_email(config, to_email, "Teste SMTP - GmapScrap", html, "Teste SMTP do GmapScrap.")
