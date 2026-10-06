"""
Pydantic schemas for users (inspectors).

These describe the shape of user data returned by the API. Records are
stored in SQLite and can be moved to another database without changing
this contract.
"""

from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str
    designation: str
    region: str
