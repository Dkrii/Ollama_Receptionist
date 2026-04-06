from pydantic import BaseModel


class EmptyPayload(BaseModel):
    pass


class DeleteDocumentPayload(BaseModel):
    path: str
