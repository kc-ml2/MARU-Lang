"""
Loader configuration models
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, Any


@dataclass
class ExtensionMapping:
    """확장자별 loader와 chunker 매핑"""
    loader: str  # 사용할 loader (parser) 이름
    chunker: str  # 사용할 chunker 이름


@dataclass
class LoaderConfig:
    """
    Loader configuration

    파일 확장자별로 어떤 loader(parser)와 chunker를 사용할지 설정
    """
    # Default loader/chunker (확장자 매핑 없을 때 사용)
    default_loader: Optional[str] = "txt"
    default_chunker: Optional[str] = "paragraph"

    # 확장자 -> {loader, chunker} 매핑
    # 예: {".pdf": {"loader": "pdf", "chunker": "paragraph"}}
    extensions: Dict[str, ExtensionMapping] = field(default_factory=dict)

    # Configuration metadata
    source_path: str = ""
    is_override: bool = False

    def __post_init__(self):
        """Post-process configuration"""
        # extensions를 dict에서 ExtensionMapping으로 변환
        new_extensions = {}
        for ext, mapping in self.extensions.items():
            if isinstance(mapping, dict):
                new_extensions[ext] = ExtensionMapping(**mapping)
            else:
                new_extensions[ext] = mapping
        self.extensions = new_extensions
