from __future__ import annotations

from pathlib import Path

from generate_repository_architecture_pdf import render_pdf_from_markdown


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent
    md_path = repo_root / "repository_architecture_detailed.md"
    pdf_path = repo_root / "repository_architecture_detailed.pdf"
    render_pdf_from_markdown(md_path=md_path, pdf_path=pdf_path)
    print(f"Wrote {pdf_path}")

