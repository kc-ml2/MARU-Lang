"""XML file parser."""

import xml.etree.ElementTree as ET
from pathlib import Path
from .base import BaseParser, ParseResult


class XMLParser(BaseParser):
    """XML 파일 파서"""

    def parse(self, file_path: Path) -> ParseResult:
        """
        XML 파일을 읽어 포맷팅된 텍스트로 변환합니다.

        Args:
            file_path: 파싱할 XML 파일 경로

        Returns:
            ParseResult: 파싱된 텍스트와 메타데이터
        """
        if not file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()

            # XML 구조를 텍스트로 변환
            lines = []
            self._element_to_text(root, lines, level=0)
            content = '\n'.join(lines)

            # 요소 개수 계산
            num_elements = len(list(root.iter()))

            metadata = {
                'file_type': 'xml',
                'encoding': tree.docinfo.encoding if hasattr(tree, 'docinfo') else 'utf-8',
                'file_size': file_path.stat().st_size,
                'root_tag': root.tag,
                'num_elements': num_elements,
            }

            # 네임스페이스 정보 추출
            namespaces = {}
            for elem in root.iter():
                if '}' in elem.tag:
                    ns = elem.tag.split('}')[0][1:]
                    if ns not in namespaces.values():
                        namespaces[f'ns{len(namespaces)}'] = ns

            if namespaces:
                metadata['namespaces'] = namespaces

            return ParseResult(content=content, metadata=metadata)

        except ET.ParseError as e:
            raise ValueError(f"XML 파싱 실패: {file_path} - {str(e)}") from e
        except Exception as e:
            raise ValueError(f"파일 읽기 실패: {file_path}") from e

    def _element_to_text(self, element: ET.Element, lines: list[str], level: int = 0) -> None:
        """
        XML 요소를 재귀적으로 텍스트로 변환합니다.

        Args:
            element: XML 요소
            lines: 결과를 저장할 리스트
            level: 들여쓰기 레벨
        """
        indent = "  " * level
        tag = element.tag

        # 네임스페이스 제거 (가독성 향상)
        if '}' in tag:
            tag = tag.split('}')[1]

        # 시작 태그와 속성
        attrs = ''
        if element.attrib:
            attrs = ' [' + ', '.join(f'{k}={v}' for k, v in element.attrib.items()) + ']'

        # 텍스트 내용
        text = (element.text or '').strip()

        if text:
            lines.append(f"{indent}<{tag}{attrs}>: {text}")
        else:
            lines.append(f"{indent}<{tag}{attrs}>")

        # 자식 요소 재귀 처리
        for child in element:
            self._element_to_text(child, lines, level + 1)

        # tail 텍스트 (닫는 태그 뒤의 텍스트)
        tail = (element.tail or '').strip()
        if tail:
            lines.append(f"{indent}  {tail}")

    def supports(self, file_path: Path) -> bool:
        """XML 파일 확장자 지원 확인"""
        return file_path.suffix.lower() in self.supported_extensions

    @property
    def supported_extensions(self) -> list[str]:
        """지원하는 XML 파일 확장자"""
        return ['.xml', '.xhtml', '.svg']
