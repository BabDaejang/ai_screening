"""DOCX 메타데이터 추출 모듈.

zipfile + xml.etree.ElementTree를 사용하여
편집 시간, 작성자, 생성/수정 일시를 추출합니다.
"""

import logging
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

logger = logging.getLogger(__name__)

# XML 네임스페이스 정의
_NS_APP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
_NS_CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_NS_DC = "http://purl.org/dc/elements/1.1/"
_NS_DCTERMS = "http://purl.org/dc/terms/"

# ElementTree에서 사용할 네임스페이스 접두사 등록
ET.register_namespace("ep", _NS_APP)
ET.register_namespace("cp", _NS_CP)
ET.register_namespace("dc", _NS_DC)
ET.register_namespace("dcterms", _NS_DCTERMS)


def _parse_xml_from_zip(zip_file: zipfile.ZipFile, xml_path: str) -> Optional[ET.Element]:
    """ZIP 내부의 XML 파일을 파싱하여 루트 엘리먼트를 반환합니다."""
    try:
        with zip_file.open(xml_path) as xml_file:
            tree = ET.parse(xml_file)
            return tree.getroot()
    except KeyError:
        logger.debug("ZIP 내 파일 없음: %s", xml_path)
        return None
    except ET.ParseError as e:
        logger.warning("XML 파싱 오류 (%s): %s", xml_path, e)
        return None


def _extract_total_time(root: Optional[ET.Element]) -> Optional[int]:
    """app.xml에서 TotalTime(편집 시간, 분) 추출."""
    if root is None:
        return None
    elem = root.find(f"{{{_NS_APP}}}TotalTime")
    if elem is not None and elem.text:
        try:
            return int(elem.text)
        except ValueError:
            logger.warning("TotalTime 값 변환 실패: %s", elem.text)
    return None


def _extract_core_properties(root: Optional[ET.Element]) -> dict:
    """core.xml에서 creator, created, modified 추출."""
    result = {"author": None, "created": None, "modified": None}
    if root is None:
        return result

    # 작성자 (dc:creator)
    creator_elem = root.find(f"{{{_NS_DC}}}creator")
    if creator_elem is not None and creator_elem.text:
        result["author"] = creator_elem.text.strip()

    # 생성 일시 (dcterms:created)
    created_elem = root.find(f"{{{_NS_DCTERMS}}}created")
    if created_elem is not None and created_elem.text:
        result["created"] = created_elem.text.strip()

    # 수정 일시 (dcterms:modified)
    modified_elem = root.find(f"{{{_NS_DCTERMS}}}modified")
    if modified_elem is not None and modified_elem.text:
        result["modified"] = modified_elem.text.strip()

    return result


def extract_docx_metadata(file_path: str) -> dict:
    """DOCX 파일에서 메타데이터를 추출합니다.

    Args:
        file_path: .docx 파일 경로.

    Returns:
        메타데이터 딕셔너리:
        {
            total_time_minutes: int|None,  # 총 편집 시간(분)
            author: str|None,              # 작성자
            created: str|None,             # 생성 일시 (ISO 8601)
            modified: str|None             # 수정 일시 (ISO 8601)
        }
    """
    default = {
        "total_time_minutes": None,
        "author": None,
        "created": None,
        "modified": None,
    }

    try:
        if not zipfile.is_zipfile(file_path):
            logger.warning("유효한 DOCX(ZIP) 파일이 아닙니다: %s", file_path)
            return default
    except OSError as e:
        logger.error("파일 접근 실패 (%s): %s", file_path, e)
        return default

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            # docProps/app.xml에서 편집 시간 추출
            app_root = _parse_xml_from_zip(zf, "docProps/app.xml")
            total_time = _extract_total_time(app_root)

            # docProps/core.xml에서 작성자, 생성/수정 일시 추출
            core_root = _parse_xml_from_zip(zf, "docProps/core.xml")
            core_props = _extract_core_properties(core_root)

            return {
                "total_time_minutes": total_time,
                "author": core_props["author"],
                "created": core_props["created"],
                "modified": core_props["modified"],
            }
    except zipfile.BadZipFile:
        logger.error("손상된 ZIP 파일: %s", file_path)
        return default
    except Exception as e:
        logger.error("메타데이터 추출 중 예상치 못한 오류 (%s): %s", file_path, e)
        return default
