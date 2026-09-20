# src/parsing/reconciler.py

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any


def intersection_area(
    a: list[float],
    b: list[float],
) -> float:

    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])

    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])

    if x1 <= x0 or y1 <= y0:
        return 0.0

    return (
        (x1 - x0)
        * (y1 - y0)
    )


def bbox_area(
    bbox: list[float],
) -> float:

    width = max(
        0.0,
        bbox[2] - bbox[0],
    )

    height = max(
        0.0,
        bbox[3] - bbox[1],
    )

    return width * height


def iou(
    a: list[float],
    b: list[float],
) -> float:

    intersection = intersection_area(
        a,
        b,
    )

    if intersection <= 0:
        return 0.0

    union = (
        bbox_area(a)
        + bbox_area(b)
        - intersection
    )

    if union <= 0:
        return 0.0

    return intersection / union


def containment_ratio(
    inner: list[float],
    outer: list[float],
) -> float:

    area = bbox_area(inner)

    if area <= 0:
        return 0.0

    return (
        intersection_area(
            inner,
            outer,
        )
        / area
    )


def text_similarity(
    a: str,
    b: str,
) -> float:

    a = " ".join(
        a.lower().split()
    )

    b = " ".join(
        b.lower().split()
    )

    if not a or not b:
        return 0.0

    return SequenceMatcher(
        None,
        a,
        b,
    ).ratio()


def horizontal_overlap(
    a: list[float],
    b: list[float],
) -> float:

    overlap = max(
        0.0,
        min(a[2], b[2])
        - max(a[0], b[0]),
    )

    return overlap


def horizontal_overlap_ratio(
    a: list[float],
    b: list[float],
) -> float:

    overlap = horizontal_overlap(
        a,
        b,
    )

    width_a = max(
        1e-9,
        a[2] - a[0],
    )

    width_b = max(
        1e-9,
        b[2] - b[0],
    )

    return overlap / min(
        width_a,
        width_b,
    )


def center_distance(
    a: list[float],
    b: list[float],
) -> float:

    ax = (a[0] + a[2]) / 2
    ay = (a[1] + a[3]) / 2

    bx = (b[0] + b[2]) / 2
    by = (b[1] + b[3]) / 2

    return (
        (ax - bx) ** 2
        + (ay - by) ** 2
    ) ** 0.5


class Reconciler:

    def __init__(
        self,
        min_match_score: float = 0.20,
    ):

        self.min_match_score = (
            min_match_score
        )

    def _candidate_score(
        self,
        pdf_block: dict[str, Any],
        paddle_block: dict[str, Any],
    ) -> float:

        pdf_bbox = pdf_block[
            "bbox_normalized"
        ]

        paddle_bbox = paddle_block[
            "bbox_normalized"
        ]

        iou_score = iou(
            pdf_bbox,
            paddle_bbox,
        )

        containment_score = containment_ratio(
            pdf_bbox,
            paddle_bbox,
        )

        text_score = text_similarity(
            pdf_block.get("text", ""),
            paddle_block.get("text", ""),
        )

        overlap_score = horizontal_overlap_ratio(
            pdf_bbox,
            paddle_bbox,
        )

        # Containment is particularly important because
        # Paddle's TABLE/FIGURE region can contain several
        # smaller PyMuPDF text blocks.
        score = (
            0.40 * iou_score
            + 0.35 * containment_score
            + 0.15 * text_score
            + 0.10 * overlap_score
        )

        return score

    def find_best_match(
        self,
        pdf_block: dict[str, Any],
        paddle_blocks: list[dict[str, Any]],
    ):

        best = None
        best_score = 0.0

        for paddle_block in paddle_blocks:

            score = self._candidate_score(
                pdf_block,
                paddle_block,
            )

            if score > best_score:

                best_score = score
                best = paddle_block

        return best, best_score

    def reconcile_page(
        self,
        pymupdf_blocks: list[dict[str, Any]],
        paddle_blocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:

        reconciled = []

        for pdf_block in pymupdf_blocks:

            match, score = (
                self.find_best_match(
                    pdf_block,
                    paddle_blocks,
                )
            )

            block = dict(
                pdf_block
            )

            if (
                match is not None
                and score >= self.min_match_score
            ):

                block["layout_label"] = (
                    match.get("label")
                )

                block["layout_text"] = (
                    match.get("text", "")
                )

                block["paddle_block_id"] = (
                    match.get(
                        "paddle_block_id"
                    )
                )

                block["paddle_order"] = (
                    match.get(
                        "reading_order"
                    )
                )

                block["paddle_bbox_normalized"] = (
                    match.get(
                        "bbox_normalized"
                    )
                )

                block["layout_match_score"] = (
                    score
                )

                block["layout_source"] = (
                    "paddleocr"
                )

            else:

                block["layout_label"] = None
                block["layout_text"] = ""
                block["paddle_block_id"] = None
                block["paddle_order"] = None
                block[
                    "paddle_bbox_normalized"
                ] = None
                block["layout_match_score"] = 0.0
                block["layout_source"] = None

            reconciled.append(
                block
            )

        return reconciled

    def reconcile(
        self,
        pymupdf_document: dict[str, Any],
        paddle_document: dict[str, Any],
    ) -> dict[str, Any]:

        pages = []

        paddle_pages = {
            page["page"]: page
            for page in paddle_document[
                "pages"
            ]
        }

        for pdf_page in pymupdf_document[
            "pages"
        ]:

            page_number = pdf_page[
                "page"
            ]

            paddle_page = paddle_pages.get(
                page_number,
                {
                    "blocks": []
                },
            )

            blocks = self.reconcile_page(
                pymupdf_blocks=pdf_page[
                    "blocks"
                ],
                paddle_blocks=paddle_page[
                    "blocks"
                ],
            )

            pages.append({
                "page": page_number,
                "width": pdf_page["width"],
                "height": pdf_page["height"],
                "blocks": blocks,
            })

        return {
            "source": pymupdf_document[
                "source"
            ],
            "parser": "pymupdf+paddleocr",
            "pages": pages,
        }