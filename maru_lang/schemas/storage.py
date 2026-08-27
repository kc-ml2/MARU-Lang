from pydantic import BaseModel


class CreateStorageRequest(BaseModel):
    name: str


class StorageResponse(BaseModel):
    id: str
    name: str
    owner_team_id: int
    owner_team_name: str
    access: str
