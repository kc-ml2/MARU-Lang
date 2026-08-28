from pydantic import BaseModel


class CreateStorageRequest(BaseModel):
    name: str


class StorageResponse(BaseModel):
    id: str
    name: str
    owner_type: str
    owner_team_id: int | None
    owner_team_name: str | None
    access: str
