"""Deliver account messages via Resend or SMTP. Uncertain sends need review."""
import os
import time
from cryptography.fernet import Fernet
from .authentication import connection,initialize
from .email_delivery import send,configured

def tick():
    with connection() as c:
        row=c.execute("SELECT * FROM public.os_email_outbox WHERE status='pending' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
        if not row:return False
        c.execute("UPDATE public.os_email_outbox SET status='sending' WHERE id=%s",(row['id'],))
    try:
        url=Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).decrypt(row['payload']['protected_url'].encode()).decode()
        subject='Confirme seu e-mail · Lo-Fi Studio OS' if row['payload']['purpose']=='verify' else 'Recupere seu acesso · Lo-Fi Studio OS'
        text='Abra este link para continuar. Ele expira em uma hora:\n\n'+url+'\n\nSe você não solicitou esta ação, ignore este e-mail.'
        message_id=send(row['recipient'],subject,text,row['id'])
        with connection() as c:
            c.execute("UPDATE public.os_email_outbox SET status='sent',sent_at=now(),provider_message_id=%s,payload=payload-'protected_url' WHERE id=%s",(message_id,row['id']))
    except Exception:
        with connection() as c:c.execute("UPDATE public.os_email_outbox SET status='uncertain' WHERE id=%s",(row['id'],))
    return True

def main():
    if not configured() or not os.getenv('STUDIO_MASTER_KEY'):
        raise RuntimeError('Configure transactional email before starting delivery')
    initialize()
    # No automatic retry of an interrupted delivery transaction.
    with connection() as c:c.execute("UPDATE public.os_email_outbox SET status='uncertain' WHERE status='sending'")
    while True:
        tick();time.sleep(3)
if __name__=='__main__':main()
