"""
Base Pipeline - 모든 파이프라인의 추상 기본 클래스
비동기 큐 기반 스트리밍으로 자유로운 진행 상황 전달
"""
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import AsyncGenerator, Any, Optional


class MessageType(str, Enum):
    """메시지 타입"""
    INFO = "info"
    ERROR = "error"
    WARNING = "warning"


@dataclass
class PipelineMessage:
    """파이프라인 진행 메시지"""
    message_type: MessageType
    message: str
    data: Any = None

    @classmethod
    def info(cls, message: str, data: Any = None):
        """INFO 메시지 생성"""
        return cls(message_type=MessageType.INFO, message=message, data=data)

    @classmethod
    def error(cls, message: str, data: Any = None):
        """ERROR 메시지 생성"""
        return cls(message_type=MessageType.ERROR, message=message, data=data)

    @classmethod
    def warning(cls, message: str, data: Any = None):
        """WARNING 메시지 생성"""
        return cls(message_type=MessageType.WARNING, message=message, data=data)


@dataclass
class PipelineComplete:
    """파이프라인 종료 신호"""
    data: Any = None  # 최종 결과


class BasePipeline(ABC):
    """모든 파이프라인의 기본 클래스 - 비동기 큐 기반 스트리밍"""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()

    async def run(self) -> AsyncGenerator[Any, None]:
        """
        파이프라인 실행 (큐 기반 스트리밍)

        백그라운드에서 process()를 실행하고,
        큐에서 메시지를 꺼내서 yield

        Yields:
            PipelineMessage | PipelineComplete: 진행 메시지 또는 완료 신호
        """
        # 백그라운드에서 process() 실행
        task = asyncio.create_task(self.process())

        try:
            while True:
                item = await self.queue.get()

                # 종료 신호 확인
                if isinstance(item, PipelineComplete):
                    yield item
                    break

                yield item
        finally:
            # process() 완료 대기
            await task

    @abstractmethod
    async def process(self):
        """
        파이프라인 주요 로직 (하위 클래스 구현)

        self.queue.put()으로 진행 상황 전달
        마지막에 반드시 PipelineComplete() 전달

        Example:
            await self.queue.put(PipelineMessage.info("Starting..."))
            # ... 처리 ...
            await self.queue.put(PipelineComplete(data=result))
        """
        pass
