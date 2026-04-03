from __future__ import annotations

import re
from pathlib import Path


def _markdown_to_lines(md_text: str) -> list[tuple[str, str]]:
    """
    Convert a small subset of Markdown into (style, line) pairs.

    Styles are:
      - 'body'
      - 'heading'
      - 'code'
    """

    lines: list[tuple[str, str]] = []
    in_code_block = False

    for raw_line in md_text.splitlines():
        line = raw_line.rstrip()

        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue

        if not line.strip():
            lines.append(("body", ""))
            continue

        if line.startswith("#"):
            heading = re.sub(r"^#+\s*", "", line).strip()
            lines.append(("heading", heading))
            continue

        if line.lstrip().startswith("- "):
            bullet = line.lstrip()[2:]
            lines.append(("body", f"- {bullet}"))
            continue

        if in_code_block:
            lines.append(("code", line))
            continue

        # Inline code -> keep the content without backticks.
        line = re.sub(r"`([^`]+)`", r"\1", line)
        # Links: [text](url) -> text (url)
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", line)
        lines.append(("body", line))

    return lines


def _wrap_by_chars(text: str, max_chars: int) -> list[str]:
    """Simple, predictable wrapping for environments without rich layout."""
    if len(text) <= max_chars:
        return [text]

    out: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        # Prefer splitting on spaces to avoid mid-word breaks.
        split_at = remaining.rfind(" ", 0, max_chars + 1)
        if split_at <= 0:
            split_at = max_chars
        out.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        out.append(remaining)
    return out


def render_pdf_from_markdown(
    md_path: Path,
    pdf_path: Path,
) -> None:
    # Imported lazily so the script can exist before installing dependencies.
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    md_text = md_path.read_text(encoding="utf-8")
    lines = _markdown_to_lines(md_text)

    page_w, page_h = A4
    margin = 40  # points
    usable_w = page_w - 2 * margin

    # These fonts are built-in and safe.
    body_font = "Helvetica"
    heading_font = "Helvetica-Bold"
    code_font = "Courier"

    body_size = 9
    heading_size = 12
    code_size = 8

    c = canvas.Canvas(str(pdf_path), pagesize=A4)

    y = page_h - margin
    line_gap = 1.1

    def new_page() -> None:
        nonlocal y
        c.showPage()
        y = page_h - margin

    # Approximate wrap widths based on font size.
    # (reportlab stringWidth isn't imported to keep this script minimal.)
    body_max_chars = max(30, int(usable_w / (body_size * 0.55)))
    code_max_chars = max(30, int(usable_w / (code_size * 0.6)))

    for style, line in lines:
        if not line:
            y -= body_size * line_gap
            if y < margin:
                new_page()
            continue

        if style == "heading":
            font = heading_font
            size = heading_size
            max_chars = body_max_chars
        elif style == "code":
            font = code_font
            size = code_size
            max_chars = code_max_chars
        else:
            font = body_font
            size = body_size
            max_chars = body_max_chars

        chunks = _wrap_by_chars(line, max_chars)

        for chunk in chunks:
            if y < margin + size * line_gap:
                new_page()
            c.setFont(font, size)
            c.drawString(margin, y, chunk)
            y -= size * line_gap

    c.save()


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent
    md_path = repo_root / "repository_architecture.md"
    pdf_path = repo_root / "repository_architecture.pdf"
    render_pdf_from_markdown(md_path=md_path, pdf_path=pdf_path)
    print(f"Wrote {pdf_path}")

