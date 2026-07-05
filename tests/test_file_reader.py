import os
import csv
import pytest
from utils.file_reader import read_submissions


def test_read_submissions_csv(tmp_path):
    # 테스트용 임시 CSV 파일 생성
    csv_file = tmp_path / "submissions.csv"
    
    # 헤더와 데이터 작성
    data = [
        ["학생명", "도서명", "독후감 내용"],
        ["김철수", "1984", "이 책은 빅 브라더에 관한 책이다. 아주 흥미롭다."],
        ["이영희", "동물농장", "동물들이 반란을 일으키는 소설이다."],
        ["박민수", "데미안", "알을 깨고 나오는 새의 이야기이다."]
    ]
    
    with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerows(data)
        
    results = read_submissions(str(csv_file))
    
    assert len(results) == 3
    
    assert results[0]["student"] == "김철수"
    assert results[0]["book_title"] == "1984"
    assert "빅 브라더" in results[0]["text"]
    assert results[0]["file_type"] == "csv_row"
    
    assert results[1]["student"] == "이영희"
    assert results[1]["book_title"] == "동물농장"
    
    assert results[2]["student"] == "박민수"
    assert results[2]["book_title"] == "데미안"


def test_read_submissions_xlsx(tmp_path):
    # openpyxl이 없으면 스킵
    try:
        import openpyxl
    except ImportError:
        pytest.skip("openpyxl is not installed")
        
    xlsx_file = tmp_path / "submissions.xlsx"
    
    wb = openpyxl.Workbook()
    ws = wb.active
    
    # 헤더와 데이터 작성
    ws.append(["이름", "책제목", "본문"])
    ws.append(["김유저", "해리포터", "해리가 마법 학교에 입학한다."])
    ws.append(["박교사", "셜록홈즈", "셜록이 미제 사건을 해결한다."])
    
    wb.save(xlsx_file)
    
    results = read_submissions(str(xlsx_file))
    
    assert len(results) == 2
    assert results[0]["student"] == "김유저"
    assert results[0]["book_title"] == "해리포터"
    assert "마법" in results[0]["text"]
    assert results[0]["file_type"] == "xlsx_row"
    
    assert results[1]["student"] == "박교사"
    assert results[1]["book_title"] == "셜록홈즈"


def test_read_submissions_txt(tmp_path):
    txt_file = tmp_path / "김철수_1984.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("이것은 김철수가 쓴 1984 독후감입니다.")
        
    results = read_submissions(str(txt_file))
    
    assert len(results) == 1
    assert results[0]["student"] == "김철수"
    assert results[0]["book_title"] == "1984"
    assert "독후감" in results[0]["text"]
    assert results[0]["file_type"] == "txt"


def test_read_submissions_dir(tmp_path):
    # 텍스트 파일 생성
    txt_file = tmp_path / "김철수_1984.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("이것은 김철수가 쓴 1984 독후감입니다.")
        
    # CSV 파일 생성
    csv_file = tmp_path / "submissions.csv"
    with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerows([
            ["학생명", "도서명", "독후감 내용"],
            ["이영희", "동물농장", "동물들이 반란을 일으키는 소설이다."]
        ])
        
    results = read_submissions(str(tmp_path))
    
    # TXT에서 1개, CSV에서 1개 총 2개 로드되어야 함
    assert len(results) == 2
    
    students = {r["student"] for r in results}
    assert "김철수" in students
    assert "이영희" in students
