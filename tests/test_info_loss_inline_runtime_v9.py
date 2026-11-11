import errno
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import info_loss_inline_runtime_v9 as runtime

class RuntimeTests(unittest.TestCase):
    def test_blocking_eagain_retries_and_nonblocking_owner_exclusion_unchanged(self):
        busy=BlockingIOError(errno.EAGAIN,'AFS lock busy')
        operation=Mock(side_effect=[busy,busy,None]);wait=[]
        runtime.blocking_flock(operation,3,fcntl.LOCK_EX,sleep=wait.append)
        self.assertEqual(operation.call_count,3);self.assertEqual(wait,[.1,.2])
        operation=Mock(side_effect=busy)
        with self.assertRaises(BlockingIOError):runtime.blocking_flock(operation,3,fcntl.LOCK_EX|fcntl.LOCK_NB,sleep=lambda s:self.fail('Nonblocking owner must never wait'))
        self.assertEqual(operation.call_count,1)
        operation=Mock(side_effect=OSError(errno.EIO,'unrelated'))
        with self.assertRaises(OSError):runtime.blocking_flock(operation,3,fcntl.LOCK_EX,sleep=lambda s:self.fail('Only EAGAIN retries'))
    def test_retry_deadline_and_signal_interrupt_are_not_swallowed(self):
        clock=[0.];operation=Mock(side_effect=BlockingIOError(errno.EAGAIN,'busy'))
        def sleep(seconds):clock[0]+=seconds
        with self.assertRaises(runtime.previous.Deadline):
            runtime.blocking_flock(operation,3,fcntl.LOCK_EX,timeout_seconds=.25,now=lambda:clock[0],sleep=sleep)
        self.assertEqual(clock[0],.25)
        def interrupt(seconds):raise runtime.previous.Deadline()
        with self.assertRaises(runtime.previous.Deadline):runtime.blocking_flock(operation,3,fcntl.LOCK_EX,sleep=interrupt)
    def test_real_signal_interrupts_blocking_retry_sleep(self):
        old=signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(runtime.previous.Deadline()))
        signal.setitimer(signal.ITIMER_REAL,.03)
        try:
            with self.assertRaises(runtime.previous.Deadline):runtime.blocking_flock(Mock(side_effect=BlockingIOError(errno.EAGAIN,'busy')),3,fcntl.LOCK_EX)
        finally:signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old)
    def test_standalone_proxy_environment_and_actual_httpx_configuration(self):
        env={'HTTPS_PROXY':'http://wrong','ALL_PROXY':'socks://wrong','all_proxy':'socks://wrong'}
        runtime.configure_proxy(env)
        self.assertEqual({env[k]for k in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy')},{runtime.PROXY})
        self.assertNotIn('ALL_PROXY',env)
        import httpx
        with httpx.Client(proxy=env['HTTPS_PROXY'],trust_env=False) as actual:
            proxy=actual._transport_for_url(httpx.URL('https://fixture/v1'))._pool._proxy_url
            self.assertEqual(proxy.host,b'10.120.0.246');self.assertEqual(proxy.port,7890)
        observed={}
        class HTTP:
            def __init__(self,**kwargs):observed.update(kwargs)
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def post(self,*args,**kwargs):
                return type('Response',(),{'status_code':200,'json':lambda self:{'choices':[{'message':{'content':'offline'},'finish_reason':'stop'}],'usage':{'total_tokens':1}}})()
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);attempt=out/'condition/attempt';attempt.mkdir(parents=True)
            model=runtime.previous.ROUTES[0];manifest={'model':model,'thinking':{'type':'disabled'},'parent_manifest':str(out/'old/manifest.json'),'max_requests':4}
            with patch.object(runtime.previous,'environment',return_value=({**env,'TOKENHUB_BASE_URL':'http://fixture/v1','TOKENHUB_API_KEY':'fixture'},{})),patch.object(runtime.previous.httpx,'Client',HTTP):
                result=runtime.previous.Client(out,manifest,attempt).call('test','fixed prompt')
            self.assertEqual(result['status'],'completed');self.assertEqual(observed['proxy'],runtime.PROXY);self.assertIs(observed['trust_env'],False)
    def test_only_exact_success_fingerprints_and_completed_conditions_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'old';new=root/'new';fingerprint='a'*64
            manifest={'cases':[{'id':'case','source_sha256':'fixed','tiled_representations':{}}],'methods':['canvas_1']}
            for n,status in [(1,'completed'),(2,'transport_error')]:
                call=old/f'conditions/case/canvas_1/attempts/attempt_{n:03d}/calls/test';call.mkdir(parents=True)
                (call/'started.json').write_text(json.dumps({'request_fingerprint':fingerprint if n==1 else 'b'*64}))
                (call/'response.json').write_text(json.dumps({'status':status,'content':'fixed'}))
            condition=old/'conditions/case/canvas_1/result.json';condition.write_text(json.dumps({'status':'failed'}));before=condition.read_bytes()
            records=runtime.reuse_successes(old,new,manifest,manifest)
            self.assertEqual(len(records),1);self.assertTrue((new/'completed-calls'/fingerprint).exists())
            self.assertFalse((new/'conditions/case/canvas_1/result.json').exists());self.assertEqual(condition.read_bytes(),before)
            self.assertFalse((new/'completed-calls'/('b'*64)).exists())
