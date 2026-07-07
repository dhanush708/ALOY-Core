import os
import struct
import logging
from typing import Dict, Any
from tools.base import BaseTool, ToolMetadata

logger = logging.getLogger(__name__)

class ImageReaderTool(BaseTool):
    """Tool for reading image metadata and basic details, with fallback to pure-Python header parsing."""
    
    def __init__(self):
        metadata = ToolMetadata(
            name="image_reader",
            description="Extract dimensions, format, and metadata from an image file.",
            category=["Images"],
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the image file relative to the workspace root."
                    }
                },
                "required": ["path"]
            },
            permissions_required=["read_file"],
            timeout_seconds=15
        )
        super().__init__(metadata)
        
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        path = params["path"]
        
        if not os.path.exists(path):
            raise FileNotFoundError(f"Image file not found: {path}")
            
        try:
            from PIL import Image
            logger.info("Using PIL for image metadata extraction.")
            try:
                with Image.open(path) as img:
                    info_summary = {k: v for k, v in img.info.items() if isinstance(v, (str, int, float))}
                    return (
                        f"Format: {img.format}\n"
                        f"Mode: {img.mode}\n"
                        f"Width: {img.width} px\n"
                        f"Height: {img.height} px\n"
                        f"Metadata: {info_summary}"
                    )
            except Exception as pil_err:
                logger.warning(f"PIL failed to open image ({pil_err}). Falling back to pure Python parser.")
                return self._parse_image_header_pure_python(path)
        except ImportError:
            logger.warning("PIL not found. Falling back to pure Python image header parsing.")
            return self._parse_image_header_pure_python(path)
            
    def _parse_image_header_pure_python(self, path: str) -> str:
        """Pure Python parsing of common image headers (PNG, JPEG, GIF, BMP) to extract dimensions."""
        size = os.path.getsize(path)
        
        try:
            with open(path, "rb") as f:
                head = f.read(30)
                
            # PNG
            if head.startswith(b"\x89PNG\r\n\x1a\n"):
                width, height = struct.unpack(">II", head[16:24])
                return f"Format: PNG (Fallback)\nDimensions: {width} x {height} px\nFile Size: {size} bytes"
                
            # GIF
            elif head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
                width, height = struct.unpack("<HH", head[6:10])
                return f"Format: GIF (Fallback)\nDimensions: {width} x {height} px\nFile Size: {size} bytes"
                
            # BMP
            elif head.startswith(b"BM"):
                width, height = struct.unpack("<ii", head[18:26])
                return f"Format: BMP (Fallback)\nDimensions: {width} x {abs(height)} px\nFile Size: {size} bytes"
                
            # JPEG
            elif head.startswith(b"\xff\xd8"):
                with open(path, "rb") as f:
                    f.read(2) # skip SOI
                    b = f.read(1)
                    while b:
                        if b == b"\xff":
                            op = f.read(1)
                            if op in (b"\xc0", b"\xc1", b"\xc2", b"\xc3"):
                                f.read(3)
                                height, width = struct.unpack(">HH", f.read(4))
                                return f"Format: JPEG (Fallback)\nDimensions: {width} x {height} px\nFile Size: {size} bytes"
                            else:
                                block_size = struct.unpack(">H", f.read(2))[0]
                                f.read(block_size - 2)
                        b = f.read(1)
                        
            return f"Format: Unknown\nFile Size: {size} bytes\n(Install 'pillow' package for advanced image reading)"
        except Exception as e:
            return f"Format: Unknown (Failed to parse: {e})\nFile Size: {size} bytes"
