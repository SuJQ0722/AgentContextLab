import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from local_reader_text_service import install_cache_observer, cache_headers, observe_cache_lookups


class ReaderCacheObserverTests(unittest.TestCase):
    def test_per_request_cache_values_remain_separate_and_jina_unknown(self):
        upstream = SimpleNamespace()

        async def fetch_async(cached):
            await asyncio.sleep(0)
            return SimpleNamespace(metadata={'from_cache': cached} if cached is not None else {})

        class Reader:
            async def read(self, cached):
                await upstream.fetch_async(cached)
                return 'html', True

            async def _fetch_with_jina(self):
                return 'jina text'

        upstream.fetch_async = fetch_async
        upstream.ReaderEngine = Reader
        context = install_cache_observer(upstream)

        async def one(cached, jina=False):
            state = {'primary': [], 'backend': None, 'cached': None}
            token = context.set(state)
            try:
                engine = Reader()
                await engine.read(cached)
                if jina:
                    await engine._fetch_with_jina()
                return cache_headers(state, True)
            finally:
                context.reset(token)

        async def run():
            return await asyncio.gather(one(True), one(False), one(None), one(True, True))

        yes, no, missing, jina = asyncio.run(run())
        self.assertEqual(yes['X-Cached'], 'true')
        self.assertEqual(no['X-Cached'], 'false')
        self.assertNotIn('X-Cached', missing)
        self.assertNotIn('X-Cached', jina)
        self.assertEqual(jina['X-ACL-Fetch-Backend'], 'jina')
        self.assertEqual(jina['X-ACL-Primary-Cache'], 'true')

    def test_failed_extraction_does_not_claim_a_returned_body_cache_hit(self):
        headers = cache_headers({'primary': [True], 'backend': 'primary-html', 'cached': True}, False)
        self.assertNotIn('X-Cached', headers)
        self.assertEqual(headers['X-ACL-Primary-Cache'], 'true')

    def test_actual_miss_lookup_is_observed_once(self):
        from contextvars import ContextVar
        context = ContextVar('test', default=None)
        values = [None, object()]
        calls = []
        def get(url):
            calls.append(url)
            return values[len(calls)-1]
        cache = SimpleNamespace(get=get)
        observe_cache_lookups(cache, context)
        state = {}; token = context.set(state)
        try:
            self.assertIsNone(cache.get('first'))
            self.assertIsNotNone(cache.get('second'))
            self.assertEqual(state['lookups'], [False, True])
            self.assertEqual(len(calls), 2)
        finally:
            context.reset(token)


if __name__ == '__main__':
    unittest.main()
