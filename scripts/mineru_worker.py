from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MinerU parsing in a subprocess")
    parser.add_argument("--file", required=True)
    parser.add_argument("--lang", default="ch")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    from src.services.document_ingestion import _mineru_parse_office, _mineru_parse_pdf_image

    result: dict = {
        "markdown": "",
        "content_list": [],
        "images_dir": None,
        "error": None,
    }
    try:
        path = Path(args.file)
        suffix = path.suffix.lower()
        file_bytes = path.read_bytes()

        if suffix in {".docx", ".pptx"}:
            result = _mineru_parse_office(file_bytes, suffix)
        elif suffix in {".pdf", ".png", ".jpg", ".jpeg"}:
            result = _mineru_parse_pdf_image(file_bytes, suffix, path.stem, args.lang)
        else:
            result["error"] = f"Unsupported file type: {suffix}"
    except Exception as exc:
        result["error"] = str(exc)

    output_path = Path(args.output)
    output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
