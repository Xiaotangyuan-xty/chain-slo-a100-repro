"""Fixed-duration open arrival stream; cancel unfinished work at the cutoff."""
import asyncio,copy,hashlib,json,os,time
from pathlib import Path

def dump(p,v):
    q=p.with_suffix('.tmp');q.write_text(json.dumps(v,ensure_ascii=False,allow_nan=False)+'\n');os.replace(q,p)

async def replay(root,stage,out,protocol,work):
    import aiohttp
    from client import StreamParser
    from client_recording import CallJSONLWriter
    from stage_replay import payload_for
    arm=os.environ['STUDY_ARM'];url='http://127.0.0.1:'+str(protocol['http_ports'][arm])+'/generate'
    H=protocol['cutoff_seconds'];writer=CallJSONLWriter(out/'client_calls.jsonl')
    calls=[];live={};origin=None;cutoff=None;closed=False;tasks=[];errors=[]
    timeout=aiohttp.ClientTimeout(total=protocol['http_request_timeout_seconds'])
    async with aiohttp.ClientSession(timeout=timeout,connector=aiohttp.TCPConnector(limit=0,force_close=True))as session:
        async def job(job,phase):
            nonlocal origin,cutoff,closed
            started=time.perf_counter();cid=job['collection_id']
            c={'phase':phase,'collection_id':cid,'request_type':job['request_type'],'application':'dr','source':job['source'],
                'received_slo':job['received_slo'],'success':False,'status':'RUNNING','stages':[],
                'client_chain_start_monotonic':started,'client_chain_end_monotonic':None,
                'arrival_offset_seconds':started-origin if phase=='main'else None,
                'planned_arrival_offset_seconds':job.get('arrival_offset_seconds')if phase=='main'else None}
            if phase=='main':live[cid]=c
            try:
                for sid,members in enumerate(job['stages']):
                    if phase=='main'and(closed or time.perf_counter()>=cutoff):raise asyncio.CancelledError()
                    stagerow={'stage_id':sid,'success':False,'requests':[]};c['stages'].append(stagerow)
                    async def request(member):
                        st=time.perf_counter();parser=StreamParser(member['prompt'])
                        r={'phase':phase,'collection_id':cid,'stage_id':sid,'request_id':member['request_id'],'request_type':2,
                            'success':False,'status':'RUNNING','target_output_tokens':member['target_output_tokens'],
                            'input_prompt_sha256':member['prompt_sha256'],'received_slo':job['received_slo'],
                            'client_request_start_monotonic':st,'client_request_end_monotonic':None,
                            'server_tbt':[],'generated_text':''}
                        stagerow['requests'].append(r)
                        try:
                            if phase=='main'and(closed or st>=cutoff):raise asyncio.CancelledError()
                            payload=payload_for(job,sid,member,phase);payload['sampling_params']['top_k']=protocol['generation']['top_k'];payload['served_time']=st-started
                            async with session.post(url,json=payload)as response:
                                if response.status!=200:raise RuntimeError('HTTP '+str(response.status)+' '+(await response.text())[:500])
                                async for chunk in response.content.iter_any():parser.feed(chunk,time.perf_counter())
                            data=parser.finish();r.update(success=True,status='COMPLETE',server_ttft=data.get('ttft'),server_tbt=data.get('tbt',[]),logged_service_gain=data.get('service_gain',0),client_first_text_monotonic=parser.first_text,stream_messages=parser.messages,generated_text=data['text'][0][len(member['prompt']):])
                        except asyncio.CancelledError:
                            r.update(status='CENSORED_AT_WINDOW_END',cutoff_censored=True)
                            if parser.last:
                                data=json.loads(parser.last);r.update(server_ttft=data.get('ttft'),server_tbt=data.get('tbt',[]),generated_text=data['text'][0][len(member['prompt']):],stream_messages=parser.messages)
                            raise
                        except Exception as exc:
                            stamp=time.perf_counter();r.update(error=repr(exc),status='ERROR'if phase=='warmup'or stamp<cutoff else'CENSORED_AT_WINDOW_END')
                            if phase=='warmup'or stamp<cutoff:errors.append({'phase':phase,'collection_id':cid,'stage_id':sid,'request_id':member['request_id'],'monotonic':stamp,'error':repr(exc)})
                        finally:r['client_request_end_monotonic']=time.perf_counter()
                        return r
                    rs=await asyncio.gather(*(request(r)for r in members));stagerow['success']=all(r['success']for r in rs)
                    if not stagerow['success']:break
                c['success']=len(c['stages'])==len(job['stages'])and all(s['success']for s in c['stages']);c['status']='COMPLETE'if c['success']else'ERROR'
            except asyncio.CancelledError:c.update(status='CENSORED_AT_WINDOW_END',cutoff_censored=True)
            finally:
                c['client_chain_end_monotonic']=time.perf_counter();calls.append(c);writer.record(c)
            return c
        try:
            for warm in work['warmup']:
                if not(await job(warm,'warmup'))['success']:raise RuntimeError('Warmup failed')
            from saturation_checks import qualify_warmup
            dump(out/'WARMUP_NATIVE_TOT_GATE.json',qualify_warmup(out,work,protocol,calls))
            origin=time.perf_counter();cutoff=origin+H
            dump(out/'MAIN_START.json',{'origin_monotonic':origin,'jobs':len(work['main']),'window_seconds':H,'last_planned_arrival_seconds':work['main'][-1]['arrival_offset_seconds'],'cutoff_monotonic':cutoff,'no_drain':True})
            async def produce():
                for item in work['main']:
                    await asyncio.sleep(max(0.,origin+item['arrival_offset_seconds']-time.perf_counter()))
                    if closed or time.perf_counter()>=cutoff:break
                    tasks.append(asyncio.create_task(job(item,'main')))
            producer=asyncio.create_task(produce())
            await asyncio.sleep(max(0.,cutoff-time.perf_counter()))
            closed=True;actual=time.perf_counter()
            snapshot={'origin_monotonic':origin,'cutoff_monotonic':cutoff,'actual_client_stop_monotonic':actual,
                'stop_lag_seconds':actual-cutoff,'window_seconds':H,'planned_roots':len(work['main']),
                'arrived_roots':len(live),'roots':copy.deepcopy(list(live.values())),
                'not_arrived_ids':[j['collection_id']for j in work['main']if j['collection_id']not in live],
                'technical_errors_before_cutoff':copy.deepcopy(errors),'policy':'Right-censor unfinished chains at fixed cutoff; do not drain.'}
            dump(out/'CLIENT_CUTOFF_SNAPSHOT.json',snapshot)
            producer.cancel()
            for task in tasks:
                if not task.done():task.cancel()
            await asyncio.gather(producer,*tasks,return_exceptions=True)
            dump(out/'CLIENT_DONE.json',{'complete':True,'window_complete':True,'full_replay_complete':False,'no_drain':True,
                'main_jobs_arrived':len(live),'observation_end_monotonic':time.perf_counter(),'cutoff_monotonic':cutoff,
                'all_local_tasks_stopped':all(t.done()for t in tasks),'technical_errors_before_cutoff':errors})
            if errors:raise RuntimeError('Technical request error before cutoff; preserve window')
        finally:writer.finish();dump(out/'client_calls.json',calls)

async def run(root,stage,out):
    protocol=json.loads((stage/'PROTOCOL.json').read_text());work=json.loads((stage/'WORKLOAD.json').read_text())
    assert protocol['cutoff_seconds']>0 and protocol['hour_stop_policy']=='cancel_at_cutoff_no_drain'
    await replay(root,stage,out,protocol,work)
if __name__=='__main__':
    import sys
    asyncio.run(run(*map(Path,sys.argv[1:4])))
