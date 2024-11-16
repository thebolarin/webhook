import secrets
from typing import List, Optional, Union

from pydantic_core.core_schema import ValidationInfo
from pydantic import AnyHttpUrl, field_validator, ConfigDict
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()
class Settings(BaseSettings):
    PROJECT_NAME: str = "TicketTailor"
    MYSQL_HOST: str
    MYSQL_USER: str
    MYSQL_PASSWORD: str
    MYSQL_DATABASE: str
    MYSQL_PORT: int
    DATABASE_URI: Optional[str] = None
    REDIS_HOST: str
    REDIS_PORT:str

    @field_validator("DATABASE_URI", mode="before")
    def assemble_db_connection(cls, v: Optional[str], info: ValidationInfo) -> str:
        if isinstance(v, str):
            return v
        
        user = info.data.get("MYSQL_USER")
        password = info.data.get("MYSQL_PASSWORD")
        host = info.data.get("MYSQL_HOST")
        port = info.data.get("MYSQL_PORT")
        database = info.data.get("MYSQL_DATABASE")
        
        if not all([user, password, host, port, database]):
            raise ValueError("MYSQL_USER, MYSQL_PASSWORD, MYSQL_HOST, and MYSQL_DATABASE must be provided to construct the database URI.")

        return f'mysql+pymysql://{user}:{password}@{host}:{port}/{database}'
    
    model_config = ConfigDict(case_sensitive = True)

settings = Settings()
