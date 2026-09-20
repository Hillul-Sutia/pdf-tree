# src/parsing/paddle_parser.py

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import os

os.environ["FLAGS_use_mkldnn"] = "0"


import pymupdf
from paddleocr import PPStructureV3

from .pymupdf_parser import normalize_bbox


class PaddleParser:
    """
    PP-StructureV3 layout parser.

    Paddle is used for:
        - layout classification
        - reading order
        - table detection
        - figure/image detection
        - caption-like regions
        - OCR/layout evidence

    PyMuPDF remains the source of authoritative PDF text.
    """

    def __init__(
        self,
        device: str = "cpu",
        dpi: int = 150,
    ):

        self.device = device
        self.dpi = dpi

        self.pipeline = PPStructureV3(
            device="cpu",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )

    def _render_page(
        self,
        page: pymupdf.Page,
        output_path: Path,
    ) -> tuple[int, int]:

        scale = self.dpi / 72.0

        matrix = pymupdf.Matrix(
            scale,
            scale,
        )

        pixmap = page.get_pixmap(
            matrix=matrix,
            alpha=False,
        )

        pixmap.save(
            str(output_path)
        )

        return (
            pixmap.width,
            pixmap.height,
        )

    @staticmethod
    def _bbox_to_list(
        bbox: Any,
    ) -> list[float]:

        if hasattr(bbox, "tolist"):
            bbox = bbox.tolist()

        bbox = list(bbox)

        return [
            float(value)
            for value in bbox
        ]

    def _parse_page(
        self,
        image_path: Path,
        page_number: int,
        image_width: int,
        image_height: int,
    ) -> dict[str, Any]:

        results = self.pipeline.predict(
            input=str(image_path)
        )

        results = list(results)

        if not results:
            return {
                "page": page_number,
                "width": image_width,
                "height": image_height,
                "blocks": [],
            }

        result = results[0]

        result_json = result.json

        if "res" in result_json:
            result_json = result_json["res"]

        parsing_results = result_json.get(
            "parsing_res_list",
            [],
        )

        blocks = []

        for index, item in enumerate(
            parsing_results
        ):

            bbox = item.get(
                "block_bbox"
            )

            if bbox is None:
                continue

            bbox = self._bbox_to_list(
                bbox
            )

            label = item.get(
                "block_label"
            )

            content = item.get(
                "block_content",
                "",
            )

            block_order = item.get(
                "block_order"
            )

            block_id = item.get(
                "block_id",
                index,
            )

            block = {
                "id": (
                    f"P{page_number + 1}"
                    f"_PADDLE_{block_id}"
                ),

                "page": page_number,

                "type": label,

                "label": label,

                "text": content or "",

                "bbox": bbox,

                "bbox_normalized": normalize_bbox(
                    bbox,
                    image_width,
                    image_height,
                ),

                "reading_order": (
                    int(block_order)
                    if block_order is not None
                    else None
                ),

                "paddle_block_id": block_id,

                "source": "paddleocr",

                "image_width": image_width,

                "image_height": image_height,
            }

            blocks.append(block)

        # Paddle's parsing_res_list is documented as being
        # in reading order. We nevertheless explicitly sort
        # by block_order when available.
        blocks.sort(
            key=lambda block: (
                block["reading_order"] is None,
                (
                    block["reading_order"]
                    if block["reading_order"] is not None
                    else 999999
                ),
            )
        )

        return {
            "page": page_number,
            "width": image_width,
            "height": image_height,
            "blocks": blocks,
        }

    def parse(
        self,
        pdf_path: str | Path,
    ) -> dict[str, Any]:

        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise FileNotFoundError(
                f"PDF not found: {pdf_path}"
            )

        document = pymupdf.open(
            pdf_path
        )

        pages = []

        with tempfile.TemporaryDirectory(
            prefix="paddle_pdf_"
        ) as temp_dir:

            temp_dir = Path(temp_dir)

            for page_number in range(
                len(document)
            ):

                page = document[
                    page_number
                ]

                image_path = (
                    temp_dir
                    / f"page_{page_number:04d}.png"
                )

                width, height = (
                    self._render_page(
                        page,
                        image_path,
                    )
                )

                page_result = (
                    self._parse_page(
                        image_path=image_path,
                        page_number=page_number,
                        image_width=width,
                        image_height=height,
                    )
                )

                pages.append(
                    page_result
                )

        document.close()

        return {
            "source": str(pdf_path),
            "parser": "paddleocr_pp_structure_v3",
            "dpi": self.dpi,
            "pages": pages,
        }

    def save(
        self,
        pdf_path: str | Path,
        output_path: str | Path,
    ):

        data = self.parse(
            pdf_path
        )

        output_path = Path(
            output_path
        )

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