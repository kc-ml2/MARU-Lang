from __future__ import annotations
from enum import Enum


class UserRoleCode(Enum):
    # 기본적으로 생성하는 코드 사용자가 만들 수 있다.
    ANONYMOUS = 'anonymous'
    EDITOR = 'editor'
    ADMIN = 'admin'
    
    @classmethod
    def is_valid_role(cls, role_name: str) -> bool:
        try:
            cls(role_name)
            return True
        except ValueError as e:
            print(e)
            return False
