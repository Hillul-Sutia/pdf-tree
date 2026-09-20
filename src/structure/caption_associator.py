# src/structure/caption_associator.py

from __future__ import annotations

import re
from typing import Any


CAPTION_PATTERN = re.compile(
    r"^\s*"
    r"(figure|fig\.|table|tab\.)"
    r"\s*"
    r"([A-Za-z]?\d+)"
    r"\s*[:.\-–—]?\s*",
    re.IGNORECASE,
)


def horizontal_overlap(
    a: list[float],
    b: list[float],
) -> float:

    return max(
        0.0,
        min(a[2], b[2])
        - max(a[0], b[0]),
    )


def overlap_ratio(
    a: list[float],
    b: list[float],
) -> float:

    overlap = horizontal_overlap(
        a,
        b,
    )

    width = min(
        a[2] - a[0],
        b[2] - b[0],
    )

    if width <= 0:
        return 0.0

    return overlap / width


def vertical_gap(
    upper: list[float],
    lower: list[float],
) -> float:

    return lower[1] - upper[3]


def looks_like_caption(
    block: dict[str, Any],
) -> bool:

    text = block.get(
        "text",
        "",
    ).strip()

    if not text:
        return False

    label = (
        block.get(
            "layout_label"
        )
        or ""
    ).lower()

    if "caption" in label:
        return True

    if CAPTION_PATTERN.match(text):
        return True

    return False


def caption_type(
    text: str,
) -> str | None:

    match = CAPTION_PATTERN.match(
        text
    )

    if not match:
        return None

    prefix = (
        match.group(1)
        .lower()
    )

    if prefix.startswith("fig"):
        return "figure"

    if prefix.startswith("tab"):
        return "table"

    return None


def element_type(
    block: dict[str, Any],
) -> str | None:

    label = (
        block.get(
            "layout_label"
        )
        or block.get(
            "type"
        )
        or ""
    ).lower()

    if "table" in label:
        return "table"

    if any(
        token in label
        for token in [
            "figure",
            "image",
            "picture",
            "chart",
        ]
    ):
        return "figure"

    if block.get("type") == "image":
        return "figure"

    return None


def caption_candidates(
    element: dict[str, Any],
    blocks: list[dict[str, Any]],
    max_vertical_gap: float = 0.08,
) -> list[dict[str, Any]]:
    """
    Find likely captions for a figure/table.

    Coordinates are normalized [0,1].
    """

    element_bbox = element[
        "bbox_normalized"
    ]

    candidates = []

    element_kind = element_type(
        element
    )

    for block in blocks:

        if block["id"] == element["id"]:
            continue

        if not looks_like_caption(
            block
        ):
            continue

        caption_bbox = block[
            "bbox_normalized"
        ]

        # Caption must be below the element.
        gap = vertical_gap(
            element_bbox,
            caption_bbox,
        )

        if gap < -0.01:
            continue

        if gap > max_vertical_gap:
            continue

        overlap = overlap_ratio(
            element_bbox,
            caption_bbox,
        )

        if overlap <= 0:
            continue

        caption_kind = caption_type(
            block.get("text", "")
        )

        type_match = (
            caption_kind is None
            or element_kind is None
            or caption_kind == element_kind
        )

        if not type_match:
            continue

        # Lower gap is better.
        # Greater horizontal overlap is better.
        score = (
            0.60 * max(
                0.0,
                1.0 - gap / max_vertical_gap,
            )
            + 0.40 * min(
                1.0,
                overlap,
            )
        )

        candidates.append({
            "caption": block,
            "score": score,
            "vertical_gap": gap,
            "horizontal_overlap": overlap,
        })

    candidates.sort(
        key=lambda item: (
            -item["score"],
            item["vertical_gap"],
        )
    )

    return candidates


def associate_captions(
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Associate each figure/table with its most likely caption.
    """

    blocks = [
        dict(block)
        for block in blocks
    ]

    block_by_id = {
        block["id"]: block
        for block in blocks
    }

    # Initialize metadata.
    for block in blocks:

        block["caption_id"] = None
        block["associated_element_id"] = None
        block["caption_confidence"] = 0.0

    used_captions = set()

    for element in blocks:

        if element_type(element) is None:
            continue

        candidates = caption_candidates(
            element,
            blocks,
        )

        for candidate in candidates:

            caption = candidate[
                "caption"
            ]

            caption_id = caption[
                "id"
            ]

            if caption_id in used_captions:
                continue

            score = candidate[
                "score"
            ]

            # Conservative threshold.
            if score < 0.45:
                continue

            element[
                "caption_id"
            ] = caption_id

            element[
                "caption_confidence"
            ] = score

            caption[
                "associated_element_id"
            ] = element["id"]

            used_captions.add(
                caption_id
            )

            break

    return blocks


def associate_document_captions(
    document: dict[str, Any],
) -> dict[str, Any]:

    output_pages = []

    for page in document["pages"]:

        blocks = associate_captions(
            page["blocks"]
        )

        output_pages.append({
            **page,
            "blocks": blocks,
        })

    return {
        **document,
        "pages": output_pages,
    }