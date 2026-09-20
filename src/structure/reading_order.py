# src/structure/reading_order.py

from __future__ import annotations

from collections import defaultdict
from typing import Any


def vertical_gap(
    a: list[float],
    b: list[float],
) -> float:

    return b[1] - a[3]


def is_below(
    a: list[float],
    b: list[float],
    tolerance: float = 0.01,
) -> bool:

    return b[1] >= a[3] - tolerance


def x_center(
    bbox: list[float],
) -> float:

    return (
        bbox[0] + bbox[2]
    ) / 2


def y_center(
    bbox: list[float],
) -> float:

    return (
        bbox[1] + bbox[3]
    ) / 2


def geometry_fallback_key(
    block: dict[str, Any],
):

    bbox = block[
        "bbox_normalized"
    ]

    return (
        bbox[1],
        bbox[0],
    )


def assign_columns(
    blocks: list[dict[str, Any]],
    gap_threshold: float = 0.04,
) -> list[dict[str, Any]]:
    """
    Lightweight column assignment.

    This is only a fallback/metadata signal.

    Paddle's reading order remains the primary signal.
    """

    if not blocks:
        return blocks

    centers = sorted(
        x_center(
            block["bbox_normalized"]
        )
        for block in blocks
    )

    if len(centers) < 3:
        for block in blocks:
            block["column"] = 0

        return blocks

    largest_gap = 0.0
    split_position = None

    for left, right in zip(
        centers,
        centers[1:],
    ):

        gap = right - left

        if gap > largest_gap:
            largest_gap = gap
            split_position = (
                left + right
            ) / 2

    if (
        split_position is None
        or largest_gap < gap_threshold
    ):

        for block in blocks:
            block["column"] = 0

        return blocks

    for block in blocks:

        center = x_center(
            block["bbox_normalized"]
        )

        block["column"] = (
            0
            if center < split_position
            else 1
        )

    return blocks


def sort_within_same_order(
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:

    return sorted(
        blocks,
        key=lambda block: (
            y_center(
                block["bbox_normalized"]
            ),
            block["bbox_normalized"][0],
        ),
    )


def apply_reading_order(
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Apply Paddle reading order while retaining geometry
    as a fallback.

    Priority:
        1. Paddle reading order
        2. geometry within identical Paddle order
        3. geometry for unmatched blocks
    """

    if not blocks:
        return []

    blocks = [
        dict(block)
        for block in blocks
    ]

    assign_columns(
        blocks
    )

    ordered_blocks = []

    grouped = defaultdict(list)

    unmatched = []

    for block in blocks:

        paddle_order = block.get(
            "paddle_order"
        )

        if paddle_order is None:
            unmatched.append(block)

        else:
            grouped[
                int(paddle_order)
            ].append(block)

    # ---------------------------------------------------------
    # Paddle ordered blocks
    # ---------------------------------------------------------

    for order in sorted(
        grouped.keys()
    ):

        group = grouped[order]

        group = sort_within_same_order(
            group
        )

        ordered_blocks.extend(
            group
        )

    # ---------------------------------------------------------
    # Unmatched blocks
    #
    # These should be inserted based on page geometry.
    # We don't simply append them to the end.
    # ---------------------------------------------------------

    for block in sorted(
        unmatched,
        key=geometry_fallback_key,
    ):

        inserted = False

        block_y = y_center(
            block["bbox_normalized"]
        )

        for index, existing in enumerate(
            ordered_blocks
        ):

            existing_y = y_center(
                existing["bbox_normalized"]
            )

            if block_y < existing_y:

                ordered_blocks.insert(
                    index,
                    block,
                )

                inserted = True
                break

        if not inserted:
            ordered_blocks.append(
                block
            )

    # ---------------------------------------------------------
    # Final metadata
    # ---------------------------------------------------------

    for final_index, block in enumerate(
        ordered_blocks
    ):

        block["final_reading_order"] = (
            final_index
        )

        paddle_order = block.get(
            "paddle_order"
        )

        if paddle_order is not None:

            block[
                "reading_order_confidence"
            ] = min(
                1.0,
                0.60
                + 0.40 * float(
                    block.get(
                        "layout_match_score",
                        0.0,
                    )
                ),
            )

        else:

            block[
                "reading_order_confidence"
            ] = 0.30

    return ordered_blocks


def apply_document_reading_order(
    document: dict[str, Any],
) -> dict[str, Any]:
    """
    Apply reading order independently to every page.
    """

    output_pages = []

    for page in document["pages"]:

        blocks = apply_reading_order(
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