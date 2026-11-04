from pydantic import BaseModel


class ExtractRequest(BaseModel):
    source_url: str
    source_ext: str
    request_id: str | None = None
    pdf_upload_url: str | None = None
