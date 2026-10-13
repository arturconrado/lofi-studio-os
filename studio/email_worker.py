"""Deliver account messages via configured SMTP. Uncertain sends need review."""
import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from cryptography.fernet import Fernet
from .authentication import connection,initialize

def tick():
    with connection() as c:
        row=c.execute("SELECT * FROM public.os_email_outbox WHERE status='pending' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
        if not row:return False
        c.execute("UPDATE public.os_email_outbox SET status='sending' WHERE id=%s",(row['id'],))
    try:
        url=Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).decrypt(row['payload']['protected_url'].encode()).decode()
        message=EmailMessage()
        message['From']=os.environ['STUDIO_EMAIL_FROM'];message['To']=row['recipient']
        message['Subject']='Confirme seu e-mail · Lo-Fi Studio OS' if row['payload']['purpose']=='verify' else 'Recupere seu acesso · Lo-Fi Studio OS'
        message.set_content('Abra este link para continuar. Ele expira em uma hora:\n\n'+url+'\n\nSe você não solicitou esta ação, ignore este e-mail.')
        port=int(os.getenv('STUDIO_SMTP_PORT','465'))
        if port not in (465,587):raise ValueError('Use authenticated TLS SMTP on port 465 or 587')
        smtp_class=smtplib.SMTP_SSL if port==465 else smtplib.SMTP
        options={'context':ssl.create_default_context()} if port==465 else {}
        with smtp_class(os.environ['STUDIO_SMTP_HOST'],port,timeout=20,**options) as smtp:
            if port==587:smtp.starttls(context=ssl.create_default_context())
            smtp.login(os.environ['STUDIO_SMTP_USER'],os.environ['STUDIO_SMTP_PASSWORD'])
            smtp.send_message(message)
        with connection() as c:
            c.execute("UPDATE public.os_email_outbox SET status='sent',sent_at=now(),payload=payload-'protected_url' WHERE id=%s",(row['id'],))
    except Exception:
        with connection() as c:c.execute("UPDATE public.os_email_outbox SET status='uncertain' WHERE id=%s",(row['id'],))
    return True

def main():
    for name in ('STUDIO_SMTP_HOST','STUDIO_SMTP_USER','STUDIO_SMTP_PASSWORD','STUDIO_EMAIL_FROM','STUDIO_MASTER_KEY'):
        if not os.getenv(name):raise RuntimeError('Configure transactional email before starting delivery')
    initialize()
    # No automatic retry of an interrupted SMTP transaction.
    with connection() as c:c.execute("UPDATE public.os_email_outbox SET status='uncertain' WHERE status='sending'")
    while True:
        tick();time.sleep(3)
if __name__=='__main__':main()
