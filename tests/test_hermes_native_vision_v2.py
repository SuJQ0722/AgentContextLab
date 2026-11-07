import base64,collections,io,sys,unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from hermes_native_vision_worker_v2 import ledger,identity,VisionRouteError

class NativeVisionLedgerTests(unittest.TestCase):
    def image(self,optimize=False,detail='high'):
        buf=io.BytesIO();Image.new('RGB',(7,9),'blue').save(buf,format='PNG',optimize=optimize)
        return {'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode(),'detail':detail}}]}
    def test_pixel_identity_preserves_detail_and_duplicate_multiplicity(self):
        a=ledger([self.image()]);b=ledger([self.image(True)])
        self.assertEqual(identity(a[0]),identity(b[0]))
        self.assertEqual(a[0]['dimensions'],[7,9])
        self.assertNotEqual(identity(a[0]),identity(ledger([self.image(detail='low')])[0]))
        missing=collections.Counter(identity(x) for x in a+a)-collections.Counter(identity(x) for x in b)
        self.assertEqual(sum(missing.values()),1)
    def test_noninline_cannot_silently_pass(self):
        with self.assertRaises(VisionRouteError):ledger([{'role':'user','content':[{'type':'image_url','image_url':{'url':'https://example.com/image.png'}}]}])
