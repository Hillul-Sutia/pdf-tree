# src/parsing/pymupdf_parser.py

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pymupdf


TEXT_BLOCK = 0
IMAGE_BLOCK = 1


def clean_text(text: str) -> str:
    """Normalize whitespace without destroying meaningful punctuation."""

    text = text.replace("\u00a0", " ")
    text = text.replace("\u200b", "")
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


def repair_hyphenation(text: str) -> str:
    """
    Repair a word split across lines.

    Example:
        fermenta-
        tion

    becomes:
        fermentation
    """

    text = re.sub(
        r"(\w)-\s*\n\s*(\w)",
        r"\1\2",
        text,
    )

    text = re.sub(
        r"\s*\n\s*",
        " ",
        text,
    )

    return clean_text(text)


def normalize_bbox(
    bbox: list[float],
    page_width: float,
    page_height: float,
) -> list[float]:
    """
    Convert PDF coordinates to [0,1] normalized coordinates.

    PyMuPDF uses:
        x → left to right
        y → top to bottom

    Returns:
        [x0, y0, x1, y1]
    """

    if page_width <= 0 or page_height <= 0:
        return [0.0, 0.0, 0.0, 0.0]

    x0, y0, x1, y1 = bbox

    return [
        max(0.0, min(1.0, x0 / page_width)),
        max(0.0, min(1.0, y0 / page_height)),
        max(0.0, min(1.0, x1 / page_width)),
        max(0.0, min(1.0, y1 / page_height)),
    ]


def get_font_flags(flags: int) -> dict[str, bool]:
    """
    Interpret PyMuPDF span font flags.
    """

    return {
        "superscript": bool(flags & 1),
        "italic": bool(flags & 2),
        "serifed": bool(flags & 4),
        "monospaced": bool(flags & 8),
        "bold": bool(flags & 16),
    }


def reconstruct_line(line: dict[str, Any]) -> dict[str, Any]:
    """
    Reconstruct a line from its spans.

    Keeps the exact span information because scientific PDFs often
    contain superscripts, Greek characters, equations, etc.
    """

    spans = line.get("spans", [])

    if not spans:
        return {
            "text": "",
            "bbox": line.get("bbox"),
            "spans": [],
        }

    ordered_spans = sorted(
        spans,
        key=lambda s: (
            s["bbox"][0],
            s["bbox"][1],
        ),
    )

    parts = []

    span_data = []

    for span in ordered_spans:

        text = span.get("text", "")

        if not text:
            continue

        parts.append(text)

        flags = get_font_flags(
            span.get("flags", 0)
        )

        span_data.append({
            "text": text,
            "bbox": list(span["bbox"]),
            "font": span.get("font"),
            "size": span.get("size"),
            "flags": span.get("flags", 0),
            **flags,
        })

    text = "".join(parts)

    return {
        "text": text,
        "bbox": list(line["bbox"]),
        "spans": span_data,
    }


def reconstruct_text_block(
    raw_block: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    """
    Reconstruct a text block from PyMuPDF lines.
    """

    lines = []

    for line in raw_block.get("lines", []):

        reconstructed = reconstruct_line(line)

        if reconstructed["text"].strip():
            lines.append(reconstructed)

    if not lines:
        return "", []

    text = "\n".join(
        line["text"]
        for line in lines
    )

    text = repair_hyphenation(text)

    return text, lines


def detect_heading(
    text: str,
    lines: list[dict[str, Any]],
    page_median_font_size: float,
) -> bool:
    """
    Conservative heading detector.

    This should not be considered final scientific heading detection.
    It is only an initial structural signal.
    """

    text = clean_text(text)

    if not text:
        return False

    if len(text) > 180:
        return False

    if len(text.split()) > 25:
        return False

    first_line = lines[0] if lines else None

    if not first_line:
        return False

    spans = first_line.get("spans", [])

    if not spans:
        return False

    max_size = max(
        float(span.get("size", 0))
        for span in spans
    )

    is_bold = any(
        span.get("bold", False)
        for span in spans
    )

    numbered = bool(
        re.match(
            r"^(?:\d+(?:\.\d+)*|[IVXLC]+)[\.\)]?\s+\S+",
            text,
            flags=re.IGNORECASE,
        )
    )

    uppercase = (
        text.upper() == text
        and any(char.isalpha() for char in text)
    )

    larger_font = (
        page_median_font_size > 0
        and max_size >= page_median_font_size * 1.15
    )

    short_bold = (
        is_bold
        and len(text.split()) <= 12
    )

    return any([
        numbered,
        uppercase and len(text.split()) <= 15,
        larger_font and len(text.split()) <= 18,
        short_bold and len(text.split()) <= 10,
    ])


class PyMuPDFParser:
    """
    Extract a scientific PDF into a page-aware block representation.

    Important:
        This parser does NOT attempt to determine the final global
        reading order. That is handled later by PaddleOCR + reconciler.
    """

    def __init__(
        self,
        pdf_path: str | Path,
    ):
        self.pdf_path = Path(pdf_path)

        if not self.pdf_path.exists():
            raise FileNotFoundError(
                f"PDF not found: {self.pdf_path}"
            )

    def parse(self) -> dict[str, Any]:

        document = pymupdf.open(self.pdf_path)

        pages = []

        for page_number, page in enumerate(document):

            page_width = float(page.rect.width)
            page_height = float(page.rect.height)

            raw = page.get_text(
                "dict",
                sort=False,
            )

            text_blocks = [
                block
                for block in raw.get("blocks", [])
                if block.get("type") == TEXT_BLOCK
            ]

            font_sizes = []

            for block in text_blocks:

                for line in block.get("lines", []):

                    for span in line.get("spans", []):

                        size = span.get("size")

                        if size:
                            font_sizes.append(
                                float(size)
                            )

            if font_sizes:
                sorted_sizes = sorted(font_sizes)
                median_size = sorted_sizes[
                    len(sorted_sizes) // 2
                ]
            else:
                median_size = 0.0

            blocks = []

            block_index = 0

            for raw_block in raw.get("blocks", []):

                raw_type = raw_block.get("type")

                # --------------------------------------------------
                # TEXT
                # --------------------------------------------------

                if raw_type == TEXT_BLOCK:

                    text, lines = reconstruct_text_block(
                        raw_block
                    )

                    if not text:
                        continue

                    bbox = list(
                        raw_block["bbox"]
                    )

                    first_line = (
                        lines[0]
                        if lines
                        else None
                    )

                    spans = []

                    for line in lines:

                        spans.extend(
                            line.get("spans", [])
                        )

                    max_font_size = (
                        max(
                            [
                                float(
                                    span.get("size", 0)
                                )
                                for span in spans
                            ],
                            default=0.0,
                        )
                    )

                    bold = any(
                        span.get("bold", False)
                        for span in spans
                    )

                    italic = any(
                        span.get("italic", False)
                        for span in spans
                    )

                    is_heading = detect_heading(
                        text=text,
                        lines=lines,
                        page_median_font_size=median_size,
                    )

                    block = {
                        "id": f"P{page_number + 1}_B{block_index}",
                        "page": page_number,
                        "type": (
                            "heading"
                            if is_heading
                            else "text"
                        ),
                        "text": text,
                        "bbox": bbox,
                        "bbox_normalized": normalize_bbox(
                            bbox,
                            page_width,
                            page_height,
                        ),
                        "width": bbox[2] - bbox[0],
                        "height": bbox[3] - bbox[1],
                        "font_size": max_font_size,
                        "bold": bold,
                        "italic": italic,
                        "lines": lines,
                        "spans": spans,
                        "source": "pymupdf",
                    }

                    blocks.append(block)

                    block_index += 1

                # --------------------------------------------------
                # IMAGE
                # --------------------------------------------------

                elif raw_type == IMAGE_BLOCK:

                    bbox = list(
                        raw_block["bbox"]
                    )

                    image_block = {
                        "id": f"P{page_number + 1}_B{block_index}",
                        "page": page_number,
                        "type": "image",
                        "text": "",
                        "bbox": bbox,
                        "bbox_normalized": normalize_bbox(
                            bbox,
                            page_width,
                            page_height,
                        ),
                        "width": bbox[2] - bbox[0],
                        "height": bbox[3] - bbox[1],
                        "image_width": raw_block.get(
                            "width"
                        ),
                        "image_height": raw_block.get(
                            "height"
                        ),
                        "ext": raw_block.get("ext"),
                        "xref": raw_block.get("xref"),
                        "source": "pymupdf",
                    }

                    blocks.append(image_block)

                    block_index += 1

                # --------------------------------------------------
                # OTHER PDF OBJECTS
                # --------------------------------------------------

                else:
                    # Do not silently throw away unknown blocks.
                    #
                    # We retain them as "other" so that later
                    # inspection can determine whether they are
                    # relevant to figures/tables/formulas.
                    bbox = raw_block.get("bbox")

                    if bbox is not None:

                        other_block = {
                            "id": f"P{page_number + 1}_B{block_index}",
                            "page": page_number,
                            "type": "other",
                            "text": "",
                            "bbox": list(bbox),
                            "bbox_normalized": normalize_bbox(
                                list(bbox),
                                page_width,
                                page_height,
                            ),
                            "source": "pymupdf",
                            "raw_type": raw_type,
                        }

                        blocks.append(other_block)

                        block_index += 1

            pages.append({
                "page": page_number,
                "width": page_width,
                "height": page_height,
                "blocks": blocks,
            })

        document.close()

        return {
            "source": str(self.pdf_path),
            "parser": "pymupdf",
            "pages": pages,
        }

    def save(
        self,
        output_path: str | Path,
    ):

        data = self.parse()

        output_path = Path(output_path)
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with open(
            output_path,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                data,
                f,
                indent=2,
                ensure_ascii=False,
            )

        return data