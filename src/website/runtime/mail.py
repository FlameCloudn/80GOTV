"""网站注册邮件的 SMTP 传输。"""

import smtplib
from email.message import EmailMessage

from src.website.runtime.config import Config


def send_registration_email(email, code):
    if not Config.SMTP_USERNAME or not Config.SMTP_PASSWORD:
        raise RuntimeError("SMTP 未配置")
    message = EmailMessage()
    message["Subject"] = "80GOTV 注册验证码"
    message["From"] = f"{Config.SMTP_FROM_NAME} <{Config.SMTP_USERNAME}>"
    message["To"] = email
    message.set_content(
        f"你的 80GOTV 注册验证码是：{code}\n\n验证码 10 分钟内有效。若不是你本人操作，请忽略此邮件。"
    )
    message.add_alternative(
        f"""<!doctype html><html><body style="font-family:Arial,sans-serif;color:#202832">
        <h2 style="margin-bottom:16px">80GOTV 注册验证</h2>
        <p>你的注册验证码是：</p>
        <p style="font-size:30px;font-weight:700;letter-spacing:6px;color:#3f698f">{code}</p>
        <p>验证码 10 分钟内有效。若不是你本人操作，请忽略此邮件。</p>
        </body></html>""",
        subtype="html",
    )
    with smtplib.SMTP_SSL(Config.SMTP_HOST, Config.SMTP_PORT, timeout=15) as smtp:
        smtp.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
        smtp.send_message(message)
