"""Independent manual program senders; each thread owns one channel context."""
import time,threading
from .core import db,init_db
from .channels import PRIMARY,CURRENT
from .radio import ctl,beat,Stopped,program_update
from .program_radio import transmit_program

def serve(cid):
 CURRENT.set(cid)
 while True:
  try:
   s=ctl();beat()
   if s['desired']=='live':
    if not s['program_id']:raise ValueError('Selecione um programa para este canal')
    transmit_program(s['program_id'])
   else:
    if s['state'] not in ('stopped','failed'):beat('stopped','Transmissão parada; envio encerrado')
    time.sleep(2)
  except Stopped:beat('stopped','Transmissão parada pelo operador')
  except Exception as e:
   beat('failed','Falha no canal; confira a conexão e a validação do programa')
   program_update("desired='stopped'");time.sleep(5)

def main():
 init_db();workers={}
 while True:
  with db() as c:ids=[r['id'] for r in c.execute('SELECT id FROM radio_channels WHERE id<>%s',(PRIMARY,)).fetchall()]
  for cid in ids:
   if cid not in workers or not workers[cid].is_alive():
    t=threading.Thread(target=serve,args=(cid,),daemon=True);workers[cid]=t;t.start()
  time.sleep(5)
if __name__=='__main__':main()
