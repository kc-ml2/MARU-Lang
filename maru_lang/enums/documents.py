from enum import IntEnum


class PermissionAction(IntEnum):
    READ = 1
    WRITE = 2
    MANAGE = 3  # sync, base_path 변경 등 관리 권한


class DocumentStatus(IntEnum):
    PROCESSING = 1  # 처리 중 (파싱/청킹/임베딩 대기)
    ACTIVE = 2      # 활성화 (임베딩 완료, 검색 가능)
    INACTIVE = 3    # 비활성화 (검색 불가)


class SyncMode(IntEnum):
    """DocumentGroup의 동기화 모드"""
    SERVER = 1  # 서버 측 VDB 사용 (기본)
    CLIENT = 2  # 클라이언트 측 VDB 사용 (MaruSync)

