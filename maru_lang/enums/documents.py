from enum import IntEnum


class DocumentStatus(IntEnum):
    PROCESSING = 1  # 처리 중 (파싱/청킹/임베딩 대기)
    ACTIVE = 2      # 활성화 (임베딩 완료, 검색 가능)
    INACTIVE = 3    # 비활성화 (검색 불가)
