"""Server-only delivery adapters. Keys never appear in response/error bodies."""
import os
import smtplib
import ssl
from email.message import EmailMessage
import httpx


def provider():
    return os.getenv('STUDIO_EMAIL_PROVIDER','smtp').strip().lower()


def resend_key():
    value=os.getenv('RESEND_API_KEY','').strip()
    return value if value.startswith('re_') and value!='re_xxxxxxxxx' else ''


def configured():
    if not os.getenv('STUDIO_EMAIL_FROM'):return False
    if provider()=='resend':return bool(resend_key())
    if provider()=='smtp':
        return all(os.getenv(name) for name in ('STUDIO_SMTP_HOST','STUDIO_SMTP_USER','STUDIO_SMTP_PASSWORD'))
    return False


def send(recipient,subject,text,event_id):
    if not configured():raise RuntimeError('Configure the selected email provider before sending')
    if provider()=='resend':
        with httpx.Client(timeout=20) as client:
            response=client.post('https://api.resend.com/emails',
                headers={'Authorization':'Bearer '+resend_key(),'Idempotency-Key':'lofi-outbox-'+str(event_id)},
                json={'from':os.environ['STUDIO_EMAIL_FROM'],'to':[recipient],'subject':subject,'text':text})
        if not response.is_success:
            raise RuntimeError('Resend rejected the request (HTTP '+str(response.status_code)+')')
        try:message_id=response.json()['id']
        except (ValueError,KeyError,TypeError):raise RuntimeError('Resend returned no message identifier') from None
        if not isinstance(message_id,str) or not message_id or len(message_id)>200:
            raise RuntimeError('Resend returned an invalid message identifier')
        return message_id
    message=EmailMessage()
    message['From']=os.environ['STUDIO_EMAIL_FROM'];message['To']=recipient;message['Subject']=subject
    message.set_content(text)
    port=int(os.getenv('STUDIO_SMTP_PORT','465'))
    if port not in (465,587):raise ValueError('Use authenticated TLS SMTP on port 465 or 587')
    smtp_class=smtplib.SMTP_SSL if port==465 else smtplib.SMTP
    options={'context':ssl.create_default_context()} if port==465 else {}
    with smtp_class(os.environ['STUDIO_SMTP_HOST'],port,timeout=20,**options) as smtp:
        if port==587:smtp.starttls(context=ssl.create_default_context())
        smtp.login(os.environ['STUDIO_SMTP_USER'],os.environ['STUDIO_SMTP_PASSWORD'])
        smtp.send_message(message)
    return None
