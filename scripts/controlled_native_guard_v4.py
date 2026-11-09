"""Exact SDK-to-final-HTTP image identity, with the reviewed model/endpoint guard.

No images are inserted by this observer. Equal encoded bytes and detail imply
unchanged native pixels. Auxiliary summaries are deliberately text-only.
"""
import contextvars,json
from hermes_bc_worker_v3 import ReviewedTextRecorder
from capture_multimodal_prefix import image_ledger

class ImageIdentityError(BaseException):pass

class ControlledRecorder(ReviewedTextRecorder):
    def install(self):
        super().install()
        import httpx
        from openai.resources.chat.completions import Completions
        sdk=Completions.create;send=httpx.Client._send_single_request
        expected=contextvars.ContextVar('controlled_expected_images',default=None)
        def create(client,*args,**kwargs):
            images=image_ledger(kwargs.get('messages',[]))
            if any(not image['inline'] for image in images):raise ImageIdentityError('Unfrozen request image')
            token=expected.set(images)
            try:return sdk(client,*args,**kwargs)
            finally:expected.reset(token)
        def wire(client,request):
            if request.url.path.rstrip('/').endswith('/chat/completions'):
                body=json.loads(request.content);images=image_ledger(body.get('messages',[]));required=expected.get()
                matched=required is not None and images==required
                self.write('controlled-wire.jsonl',{'event':'final_http_request','purpose':self.purpose.get(),
                    'model':body.get('model'),'images':images,'expected_image_count':len(required) if required is not None else None,
                    'exact_sdk_image_identity':matched,'request_sent':matched})
                if not matched:self.invalid=True;raise ImageIdentityError('Final HTTP image count/bytes/detail mismatch')
            return send(client,request)
        Completions.create=create;httpx.Client._send_single_request=wire
