import copy,math

def arrivals(base,rate):
 assert rate>0 and base and base[-1]>0
 return [float(x)*len(base)/(rate*base[-1])for x in base]

def choose(rows):
 assert rows and all(r['gate']=='PASS'for r in rows)
 best=max(r['goodput']for r in rows)
 if not math.isfinite(best)or best<=0:raise ValueError('No positive finite calibration goodput')
 eligible=[r for r in rows if r['goodput']>=.95*best]
 return min(eligible,key=lambda r:r['rate']),best

def normal_blocks(profiled):
 assert profiled>=4096,'Profiled KV unexpectedly small; preserve evidence and stop'
 n=int(profiled*.9)//64*64
 assert n>=2048 and n>512
 return n


def ports(slot):
 assert 0<=slot<40
 return 29400+2*slot,65470+slot
