"""DSH segment-label adapter, retaining all original bridge integrity checks."""
from unittest.mock import patch
import inline_visual_transport_v1 as inline
import dsh_inline_transport_bridge_v1 as parent
from dsh_canvas_segments_v13 import select_canvas_pages
if __name__ == '__main__':
    with patch.object(inline,'select_canvas_pages',select_canvas_pages): parent.main()
