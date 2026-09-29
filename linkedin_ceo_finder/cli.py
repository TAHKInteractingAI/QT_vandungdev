"""Command Line Interface (CLI) cho LinkedIn CEO Finder."""

import argparse
import sys
from typing import List
import orjson

from .config import DEFAULT_SHEET_ID, DEFAULT_WORKSHEET_NAME
from .core import find_ceos_by_domains, find_ceos_by_keyword


def parse_args(args: List[str] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LinkedIn CEO Finder - Công cụ tìm kiếm thông tin CEO / Lãnh đạo cấp cao từ Domain hoặc Keyword."
    )

    subparsers = parser.add_subparsers(dest="command", help="Chế độ tìm kiếm")

    # Mode 1: Domain search
    domain_parser = subparsers.add_parser("domains", help="Tìm kiếm CEO từ danh sách tên miền")
    domain_parser.add_argument(
        "domains",
        nargs="+",
        help="Danh sách tên miền (vd: google.com nvidia.com)",
    )
    domain_parser.add_argument(
        "--target-count",
        "-t",
        type=int,
        default=None,
        help="Số lượng CEO tối đa cần lấy",
    )
    domain_parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=5,
        help="Số luồng chạy song song (mặc định: 5)",
    )

    # Mode 2: Keyword search
    keyword_parser = subparsers.add_parser("keyword", help="Tìm kiếm CEO theo từ khóa ngành nghề")
    keyword_parser.add_argument(
        "keyword",
        type=str,
        help="Từ khóa tìm kiếm (vd: 'AI Vietnam', 'Fintech')",
    )
    keyword_parser.add_argument(
        "--target-count",
        "-t",
        type=int,
        default=10,
        help="Số lượng CEO mục tiêu (mặc định: 10)",
    )
    keyword_parser.add_argument(
        "--max-pages",
        "-p",
        type=int,
        default=10,
        help="Số trang tìm kiếm tối đa duyệt qua (mặc định: 10)",
    )
    keyword_parser.add_argument(
        "--skip-empty-company",
        action="store_true",
        help="Bỏ qua nếu không trích xuất được tên công ty",
    )

    # Chung cho cả 2 mode
    for p in [domain_parser, keyword_parser]:
        p.add_argument(
            "--no-sheet",
            action="store_true",
            help="Không lưu vào Google Sheet",
        )
        p.add_argument(
            "--sheet-id",
            type=str,
            default=DEFAULT_SHEET_ID,
            help="ID của Google Sheet",
        )
        p.add_argument(
            "--worksheet",
            type=str,
            default=DEFAULT_WORKSHEET_NAME,
            help="Tên worksheet/tab trong Google Sheet",
        )
        p.add_argument(
            "--output",
            "-o",
            type=str,
            default=None,
            help="Đường dẫn file JSON xuất kết quả nếu cần lưu file cục bộ",
        )

    return parser.parse_args(args)


def main(args: List[str] = None) -> int:
    parsed = parse_args(args)
    if not parsed.command:
        print("❌ Lỗi: Vui lòng chọn chế độ 'domains' hoặc 'keyword'.")
        print("Chạy 'python -m linkedin_ceo_finder.cli --help' để xem hướng dẫn.")
        return 1

    save_to_sheet = not parsed.no_sheet
    results = []

    try:
        if parsed.command == "domains":
            results = find_ceos_by_domains(
                company_domains=parsed.domains,
                target_count=parsed.target_count,
                save_to_sheet=save_to_sheet,
                max_workers=parsed.workers,
                sheet_id=parsed.sheet_id,
                worksheet_name=parsed.worksheet,
            )
        elif parsed.command == "keyword":
            results = find_ceos_by_keyword(
                keyword=parsed.keyword,
                target_count=parsed.target_count,
                save_to_sheet=save_to_sheet,
                sheet_id=parsed.sheet_id,
                worksheet_name=parsed.worksheet,
                skip_empty_company=parsed.skip_empty_company,
                max_pages=parsed.max_pages,
            )

        if parsed.output:
            data = [r.to_dict() for r in results]
            with open(parsed.output, "wb") as f:
                f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))
            print(f"💾 Đã xuất {len(results)} kết quả ra file: {parsed.output}")

        return 0
    except KeyboardInterrupt:
        print("\n🛑 Quá trình tìm kiếm đã bị dừng bởi người dùng.")
        return 130
    except Exception as e:
        print(f"\n❌ Lỗi hệ thống: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
