"""제출물 파일 읽기 모듈.

디렉토리 내 파일 읽기뿐만 아니라, 단일 Excel(.xlsx), CSV, PDF, TXT, DOCX 파일 업로드 및 분석을 지원합니다.
Excel/CSV의 경우 여러 학생의 기록이 들어있는 테이블(Table) 형태로 처리합니다.
"""

import os
import csv
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _read_txt(file_path: str) -> Optional[str]:
    """텍스트 파일을 읽습니다. UTF-8 → CP949 순서로 시도합니다."""
    for encoding in ("utf-8", "cp949"):
        try:
            with open(file_path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except OSError as e:
            logger.error("파일 읽기 실패 (%s): %s", file_path, e)
            return None
    logger.warning("인코딩 감지 실패, errors='replace'로 읽기 시도: %s", file_path)
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        logger.error("파일 읽기 최종 실패 (%s): %s", file_path, e)
        return None


def _read_docx(file_path: str) -> Optional[str]:
    """python-docx를 사용하여 .docx 파일의 본문 텍스트를 추출합니다."""
    try:
        from docx import Document
    except ImportError:
        logger.error("python-docx가 설치되지 않았습니다. pip install python-docx")
        return None

    try:
        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as e:
        logger.error("DOCX 읽기 실패 (%s): %s", file_path, e)
        return None


def _read_pdf(file_path: str) -> Optional[str]:
    """pypdf를 사용하여 PDF 파일의 텍스트를 추출합니다."""
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.error("pypdf 패키지가 설치되지 않았습니다. pip install pypdf")
        return None
    try:
        reader = PdfReader(file_path)
        pages_text = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages_text.append(t)
        return "\n".join(pages_text)
    except Exception as e:
        logger.error("PDF 읽기 실패 (%s): %s", file_path, e)
        return None


def _parse_filename(filename: str) -> tuple[str, Optional[str]]:
    """파일 이름에서 학생 식별자와 도서명을 분리합니다.

    형식: identifier_booktitle.ext → (identifier, booktitle)
    그 외: filename → (filename, None)
    """
    stem = Path(filename).stem
    if "_" in stem:
        parts = stem.split("_", maxsplit=1)
        identifier = parts[0].strip()
        book_title = parts[1].strip() if parts[1].strip() else None
        return identifier, book_title
    return stem, None


def _parse_tabular_rows(rows: list[list[str]], file_path: str) -> list[dict]:
    """Excel/CSV 행 데이터에서 학생명, 도서명, 본문 컬럼을 자동 매핑하여 읽어들입니다."""
    if not rows:
        return []
    
    # 첫 행을 헤더로 파싱
    header = [str(cell).strip() for cell in rows[0]]
    
    # 매핑 후보 헤더 리스트
    student_headers = ["학생", "학생명", "이름", "학번", "작성자", "제출자", "이름/학번", "name", "student", "author"]
    book_headers = ["도서명", "책", "책제목", "도서", "제목", "book", "title"]
    text_headers = ["내용", "본문", "제출물", "독후감", "글", "에세이", "text", "content", "essay"]
    
    student_idx = -1
    book_idx = -1
    text_idx = -1
    
    for i, col in enumerate(header):
        col_lower = col.lower()
        if student_idx == -1 and any(h in col_lower for h in student_headers):
            student_idx = i
        elif book_idx == -1 and any(h in col_lower for h in book_headers):
            book_idx = i
        elif text_idx == -1 and any(h in col_lower for h in text_headers):
            text_idx = i
            
    # 헤더 단어 매칭 실패 시 기본값 매핑
    if student_idx == -1:
        student_idx = 0
    if text_idx == -1:
        text_idx = min(2, len(header) - 1) if len(header) > 2 else (1 if len(header) > 1 else 0)
    if book_idx == -1 and len(header) > 2:
        book_idx = 1
        
    results = []
    
    # 데이터 행 추출
    for r_idx in range(1, len(rows)):
        row = rows[r_idx]
        if not row:
            continue
            
        student_val = row[student_idx] if student_idx < len(row) else f"학생_{r_idx}"
        book_val = row[book_idx] if (book_idx != -1 and book_idx < len(row)) else None
        text_val = row[text_idx] if text_idx < len(row) else ""
        
        student_val = str(student_val).strip()
        book_val = str(book_val).strip() if book_val else None
        text_val = str(text_val).strip()
        
        if not student_val or not text_val:
            continue
            
        results.append({
            "student": student_val,
            "book_title": book_val,
            "text": text_val,
            "file_path": file_path,
            "file_type": "csv_row" if file_path.endswith(".csv") else "xlsx_row",
        })
        
    logger.info("표 형식 제출물 파싱 완료: %s 에서 %d행 추출", Path(file_path).name, len(results))
    return results


def _read_csv_file(file_path: str) -> list[dict]:
    """CSV 파일을 읽어서 학생 리스트를 반환합니다."""
    rows = []
    # UTF-8, CP949 인코딩 시도
    for encoding in ("utf-8-sig", "cp949", "utf-8"):
        try:
            with open(file_path, "r", encoding=encoding) as f:
                reader = csv.reader(f)
                rows = list(reader)
            break
        except UnicodeDecodeError:
            continue
        except OSError as e:
            logger.error("CSV 읽기 실패: %s", e)
            return []
            
    return _parse_tabular_rows(rows, file_path)


def _read_xlsx_file(file_path: str) -> list[dict]:
    """Excel(.xlsx) 파일을 읽어서 학생 리스트를 반환합니다."""
    try:
        import openpyxl
    except ImportError:
        logger.error("openpyxl 패키지가 설치되지 않았습니다. pip install openpyxl")
        return []
        
    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
        sheet = wb.active
        rows = []
        for r in sheet.iter_rows(values_only=True):
            # 행 전체가 None인 경우 패스
            if any(cell is not None for cell in r):
                rows.append(list(r))
        return _parse_tabular_rows(rows, file_path)
    except Exception as e:
        logger.error("Excel 읽기 에러 (%s): %s", file_path, e)
        return []


def read_submissions(submissions_path_or_dir: str) -> list[dict]:
    """제출물 경로(디렉토리 또는 파일, 또는 세미콜론으로 구분된 다중 파일)에서 학생 제출물을 읽어 목록을 반환합니다.

    Args:
        submissions_path_or_dir: 제출물이 저장된 디렉토리 또는 단일 파일 경로, 혹은 세미콜론 구분 경로.

    Returns:
        제출물 정보 딕셔너리 목록.
    """
    if not submissions_path_or_dir:
        return []
        
    # 세미콜론(;)으로 연결된 다중 파일 경로 처리
    if ";" in submissions_path_or_dir:
        results = []
        paths = submissions_path_or_dir.split(";")
        for p_str in paths:
            p_str = p_str.strip()
            if not p_str:
                continue
            results.extend(read_submissions(p_str))
        return results

    path = Path(submissions_path_or_dir)
    if not path.exists():
        logger.error("제출물 경로가 존재하지 않습니다: %s", submissions_path_or_dir)
        return []

    # 1. 단일 파일인 경우 처리
    if path.is_file():
        ext = path.suffix.lower()
        if ext == ".csv":
            return _read_csv_file(str(path))
        elif ext in (".xlsx", ".xls"):
            return _read_xlsx_file(str(path))
        elif ext == ".pdf":
            text = _read_pdf(str(path))
            student, book_title = _parse_filename(path.name)
            if text and text.strip():
                return [{
                    "student": student,
                    "book_title": book_title,
                    "text": text,
                    "file_path": str(path),
                    "file_type": "pdf"
                }]
            return []
        elif ext == ".txt":
            text = _read_txt(str(path))
            student, book_title = _parse_filename(path.name)
            if text and text.strip():
                return [{
                    "student": student,
                    "book_title": book_title,
                    "text": text,
                    "file_path": str(path),
                    "file_type": "txt"
                }]
            return []
        elif ext == ".docx":
            text = _read_docx(str(path))
            student, book_title = _parse_filename(path.name)
            if text and text.strip():
                return [{
                    "student": student,
                    "book_title": book_title,
                    "text": text,
                    "file_path": str(path),
                    "file_type": "docx"
                }]
            return []
        else:
            logger.error("지원하지 않는 파일 형식입니다: %s", path.name)
            return []

    # 2. 디렉토리인 경우 처리
    results: list[dict] = []
    supported_extensions = {".txt", ".docx", ".pdf", ".xlsx", ".xls", ".csv"}

    files = sorted(path.iterdir())
    for file_path in files:
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        if ext not in supported_extensions:
            continue

        if ext == ".csv":
            results.extend(_read_csv_file(str(file_path)))
        elif ext in (".xlsx", ".xls"):
            results.extend(_read_xlsx_file(str(file_path)))
        else:
            student, book_title = _parse_filename(file_path.name)

            if ext == ".txt":
                text = _read_txt(str(file_path))
                file_type = "txt"
            elif ext == ".docx":
                text = _read_docx(str(file_path))
                file_type = "docx"
            elif ext == ".pdf":
                text = _read_pdf(str(file_path))
                file_type = "pdf"
            else:
                continue

            if text is None or not text.strip():
                continue

            results.append({
                "student": student,
                "book_title": book_title,
                "text": text,
                "file_path": str(file_path),
                "file_type": file_type,
            })

    logger.info("총 %d개 제출물 읽기 완료 (디렉토리: %s)", len(results), submissions_path_or_dir)
    return results
