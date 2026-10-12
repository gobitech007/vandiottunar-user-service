import logging

from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings

logger = logging.getLogger("vandi.ocr")


class OcrUnavailable(Exception):
    pass


def _textract_text(data: bytes) -> str:
    import boto3

    client = boto3.client("textract", region_name=get_settings().aws_region)
    result = client.detect_document_text(Document={"Bytes": data})
    return "\n".join(b["Text"] for b in result.get("Blocks", []) if b.get("BlockType") == "LINE")


async def read_text(data: bytes) -> str:
    """OCR one image or single-page PDF on the server. Raises OcrUnavailable when not configured."""
    if get_settings().ocr_provider != "textract":
        raise OcrUnavailable("Server OCR is not enabled")
    return await run_in_threadpool(_textract_text, data)
