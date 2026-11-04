"""Runtime configuration for the converter service."""

import os
from dataclasses import dataclass

OFFICE_EXTENSIONS = frozenset({"pptx", "ppt", "docx", "doc"})
PDF_EXTENSIONS = frozenset({"pdf"})
SUPPORTED_EXTENSIONS = OFFICE_EXTENSIONS | PDF_EXTENSIONS

OPENDATALOADER_ENGINE = "opendataloader"
PDF_INSPECTOR_ENGINE = "pdf-inspector"


@dataclass
class ConverterConfig:
    """Env-derived settings plus the safety bounds applied to untrusted extractor output."""

    secret: str
    s3_bucket: str
    s3_region: str
    pdf_engine: str
    max_concurrent_extractions: int
    convert_timeout_seconds: int = 120
    extract_timeout_seconds: int = 180
    max_source_bytes: int = 200 * 1024 * 1024
    max_extraction_json_bytes: int = 64 * 1024 * 1024
    max_extraction_elements: int = 100_000
    max_element_children: int = 10_000
    max_element_text_bytes: int = 1024 * 1024
    max_element_depth: int = 16
    max_extracted_text_bytes: int = 32 * 1024 * 1024
    max_extraction_response_bytes: int = 40 * 1024 * 1024
    max_pages: int = 10_000

    @classmethod
    def from_env(cls) -> "ConverterConfig":
        secret = os.environ.get("CONVERTER_SECRET", "")
        if not secret:
            raise RuntimeError(
                "CONVERTER_SECRET environment variable is required. "
                "Generate a random string and set it on both the API and converter services."
            )
        pdf_engine = os.environ.get("PDF_ENGINE", OPENDATALOADER_ENGINE).strip() or OPENDATALOADER_ENGINE
        if pdf_engine not in (OPENDATALOADER_ENGINE, PDF_INSPECTOR_ENGINE):
            raise RuntimeError(
                f"PDF_ENGINE must be '{OPENDATALOADER_ENGINE}' or '{PDF_INSPECTOR_ENGINE}', got {pdf_engine!r}"
            )
        return cls(
            secret=secret,
            s3_bucket=os.environ.get("S3_BUCKET", ""),
            s3_region=os.environ.get("AWS_REGION", "us-east-1"),
            pdf_engine=pdf_engine,
            max_concurrent_extractions=max(1, int(os.environ.get("MAX_CONCURRENT_EXTRACTIONS", "2"))),
        )
