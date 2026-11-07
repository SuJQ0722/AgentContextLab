import io
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from rq3_pdf_renderer import stripe_crop_box,trusted_pillow_limit,MAX_PAGE_PIXELS,install,page_pixels

class BoundedPDFTests(unittest.TestCase):
    def test_exact_crop_across_stripes_and_half_median(self):
        for seed in range(5):
            array=np.full((2060,41),250,dtype=np.uint8)
            array[:2,:2]=[[250,249],[250,249]]
            array[1023:1026,3+seed:12+seed]=244
            array[2049,35]=240
            img=Image.fromarray(array)
            mask=np.abs(array.astype(float)-float(np.median(array[:2,:2])))>5
            cols=np.where(mask.any(axis=0))[0];rows=np.where(mask.any(axis=1))[0]
            expected=(max(0,int(cols[0])-1),max(0,int(rows[0])-1),min(img.width,int(cols[-1])+2),min(img.height,int(rows[-1])+2))
            self.assertEqual(stripe_crop_box(img),expected)
        self.assertIsNone(stripe_crop_box(Image.new('RGB',(5,5),'white')))
    def test_limit_restores_even_on_error(self):
        before=Image.MAX_IMAGE_PIXELS
        with self.assertRaises(RuntimeError):
            with trusted_pillow_limit():
                self.assertEqual(Image.MAX_IMAGE_PIXELS,MAX_PAGE_PIXELS);raise RuntimeError('fixture')
        self.assertEqual(Image.MAX_IMAGE_PIXELS,before)
    def test_normal_document_calls_original(self):
        def original(*a,**kw):return ['unchanged']
        module=SimpleNamespace(_pdf_bytes_to_image_b64_list=original)
        with patch('rq3_pdf_renderer.page_pixels',return_value=[100]):
            install(module);self.assertEqual(module._pdf_bytes_to_image_b64_list(b'fixture'),['unchanged'])
    def test_large_route_threshold_preserves_typical_core_canvas(self):
        original=lambda *a,**kw:['original']
        module=SimpleNamespace(_pdf_bytes_to_image_b64_list=original);install(module)
        with patch('rq3_pdf_renderer.page_pixels',return_value=[31_000_000]):
            self.assertEqual(module._pdf_bytes_to_image_b64_list(b'fixture'),['original'])
        with patch('rq3_pdf_renderer.page_pixels',return_value=[100_000_001]),patch('rq3_pdf_renderer.convert_pdf_bounded',return_value=['bounded']) as bounded:
            self.assertEqual(module._pdf_bytes_to_image_b64_list(b'fixture'),['bounded'])
            bounded.assert_called_once()
    def test_rejects_oversized_page_before_raster(self):
        with patch('pdf2image.pdfinfo_from_bytes',side_effect=[{'Pages':1},{'Page    1 size':'25000 x 25000 pts'}]):
            with self.assertRaisesRegex(ValueError,'pixel cap'):page_pixels(b'fixture')
