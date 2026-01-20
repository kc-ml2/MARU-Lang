import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import AsyncGenerator, Any, Optional, Union


class MessageType(str, Enum):
    """enum for pipeline message types"""
    INFO = "info"
    DEBUG = "debug"
    NORMAL = "normal"
    ERROR = "error"
    WARNING = "warning"
    COMPLETE = "complete"


@dataclass
class PipelineMessage:
    """파이프라인 진행 메시지"""
    message_type: MessageType
    message: Union[str, AsyncGenerator[str, None]]
    data: Any = None

    @classmethod
    def normal(cls, message: Union[str, AsyncGenerator[str, None]], data: Any = None):
        """NORMAL 메시지 생성"""
        return cls(message_type=MessageType.NORMAL, message=message, data=data)

    @classmethod
    def info(cls, message: str, data: Any = None):
        """INFO 메시지 생성"""
        return cls(message_type=MessageType.INFO, message=message, data=data)

    @classmethod
    def debug(cls, message: str, data: Any = None):
        """DEBUG 메시지 생성"""
        return cls(message_type=MessageType.DEBUG, message=message, data=data)

    @classmethod
    def error(cls, message: str, data: Any = None):
        """ERROR 메시지 생성"""
        return cls(message_type=MessageType.ERROR, message=message, data=data)

    @classmethod
    def warning(cls, message: str, data: Any = None):
        """WARNING 메시지 생성"""
        return cls(message_type=MessageType.WARNING, message=message, data=data)

    @classmethod
    def complete(cls, data: Any = None):
        """COMPLETE 메시지 생성"""
        return cls(message_type=MessageType.COMPLETE, message="", data=data)


class BasePipeline(ABC):
    """모든 파이프라인의 기본 클래스 - 비동기 큐 기반 스트리밍"""

    def __init__(self):
        self.queue: asyncio.Queue[PipelineMessage] = asyncio.Queue()

    async def run(self, *args, **kwargs) -> AsyncGenerator[PipelineMessage, None]:
        """
        execute pipeline (base on queue streaming)
        Yields:
            PipelineMessage
        """
        task = asyncio.create_task(self.process(*args, **kwargs))

        try:
            while True:
                item = await self.queue.get()
                # 종료 신호 확인
                yield item
                if item.message_type == MessageType.COMPLETE:
                    break
        finally:
            # process() 완료 대기
            await task

    @abstractmethod
    async def process(
        self,
        *args,
        **kwargs
    ):
        """
        should put PipelineMessage into self.queue to report progress.
        important: 
        Example:
            await self.queue.put(PipelineMessage.info("Starting..."))
            # ... progress ...
            await self.queue.put(PipelineMessage.complete())
        """
        pass
