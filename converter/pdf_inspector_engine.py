"""Per-page markdown extraction via the pure-Rust pdf-inspector."""

import sys

from converter import process_group
from converter.bounds import bounded_utf8_size, ensure_bounded_json, read_bounded_json
from converter.config import PDF_INSPECTOR_ENGINE, ConverterConfig

# No JVM here, but a hung parse still needs the same killable-process-group bound.
_WORKER_SCRIPT = (
    "import sys, json, pdf_inspector\n"
    "result = pdf_inspector.extract_pages_markdown(sys.argv[1])\n"
    "pages = [{'page': p.page + 1, 'content': p.markdown or ''} for p in result.pages]\n"
    "with open(sys.argv[2] + '/result.json', 'w', encoding='utf-8') as handle:\n"
    "    json.dump({'pages': pages}, handle)\n"
)


class PdfInspectorEngine:
    name = PDF_INSPECTOR_ENGINE

    def __init__(self, config: ConverterConfig) -> None:
        self._config = config

    def extract_pages(self, pdf_path: str, output_dir: str) -> list[dict]:
        process_group.run_in_process_group(
            [sys.executable, "-c", _WORKER_SCRIPT, pdf_path, output_dir],
            timeout=self._config.extract_timeout_seconds,
            what=self.name,
        )
        data = read_bounded_json(output_dir, self.name, self._config.max_extraction_json_bytes)
        pages = self._validated_pages(data)
        ensure_bounded_json(pages, self._config.max_extraction_response_bytes, "extraction response")
        return pages

    def _validated_pages(self, data: dict) -> list[dict]:
        raw_pages = data.get("pages", [])
        if not isinstance(raw_pages, list):
            raise RuntimeError("pdf-inspector pages must be a list")
        if len(raw_pages) > self._config.max_pages:
            raise RuntimeError("pdf-inspector produced too many pages")

        pages = []
        total_text_bytes = 0
        for entry in raw_pages:
            if not isinstance(entry, dict):
                raise RuntimeError("pdf-inspector pages must be objects")
            page_num = entry.get("page")
            if type(page_num) is not int or page_num < 1:
                raise RuntimeError("pdf-inspector page numbers must be positive integers")
            content = entry.get("content", "")
            remaining = self._config.max_extracted_text_bytes - total_text_bytes
            total_text_bytes += bounded_utf8_size(content, remaining, "total extracted text")
            pages.append({"page": page_num, "content": content})
        return pages
