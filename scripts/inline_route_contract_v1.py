"""Explicit approved direct-image transport and four-channel route contract."""
ROUTES = [
    'deepseek-v4.1-flash-1017/huoshan/huoshan',
    'deepseek-v4.1-flash-1017/zijian/sfb',
    'deepseek-v4.1-flash-1017/huoshan/sfc',
    'deepseek-v4.1-flash-1017/zijian/sfc',
]


def validate_routes(spec, config):
    for value in (spec, config):
        if value.get('model_route_policy') != 'four-route-rotation-v1' or value.get('approved_model_routes') != ROUTES:
            raise ValueError('Exact approved four-model route contract required')
        if value.get('image_transport') != 'inline-recent-ten-chunked-v1' or value.get('transport_delivery_version') != 'inline-direct-v1':
            raise ValueError('Explicit inline direct image transport required')
        if value.get('transport_runtime_version') != 'visual-transport-runtime-v3':
            raise ValueError('Explicit route-aware transport runtime required')
        if value.get('model') != ROUTES[0]:
            raise ValueError('Original experimental model identity must be retained')
