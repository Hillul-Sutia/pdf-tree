# src/parsing/parse_document.py

from pathlib import Path
import json

from .pymupdf_parser import PyMuPDFParser
from .paddle_parser import PaddleParser
from .reconciler import Reconciler
from ..structure.reading_order import (
    apply_document_reading_order,
)
from ..structure.caption_associator import (
    associate_document_captions,
)


def parse_document(
    pdf_path: str,
    output_dir: str = "data/processed",
    paddle_device: str = "cpu",
):

    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ---------------------------------------------------------
    # 1. PyMuPDF
    # ---------------------------------------------------------

    pymupdf_parser = PyMuPDFParser(
        pdf_path
    )

    pymupdf_document = (
        pymupdf_parser.parse()
    )

    with open(
        output_dir / "pymupdf.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            pymupdf_document,
            f,
            indent=2,
            ensure_ascii=False,
        )

    # ---------------------------------------------------------
    # 2. PaddleOCR
    # ---------------------------------------------------------

    paddle_parser = PaddleParser(
        device=paddle_device,
        dpi=150,
    )

    paddle_document = paddle_parser.parse(
        pdf_path
    )

    with open(
        output_dir / "paddle.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            paddle_document,
            f,
            indent=2,
            ensure_ascii=False,
        )

    # ---------------------------------------------------------
    # 3. Reconcile
    # ---------------------------------------------------------

    reconciler = Reconciler()

    document = reconciler.reconcile(
        pymupdf_document,
        paddle_document,
    )

    # ---------------------------------------------------------
    # 4. Reading order
    # ---------------------------------------------------------

    document = (
        apply_document_reading_order(
            document
        )
    )

    # ---------------------------------------------------------
    # 5. Caption association
    # ---------------------------------------------------------

    document = (
        associate_document_captions(
            document
        )
    )

    # ---------------------------------------------------------
    # 6. Save final representation
    # ---------------------------------------------------------

    final_path = (
        output_dir
        / "reconciled_document.json"
    )

    with open(
        final_path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            document,
            f,
            indent=2,
            ensure_ascii=False,
        )

    return document


if __name__ == "__main__":

    file_path = r"E:\HILLUL\Project Associate - I\SDEP\Indigenous fermented foods of Northeast India Emerging opportunities in functional foods, microbiota-driven nutrition and safety perspectives.pdf"
    document = parse_document(
        pdf_path=(
            file_path
        ),
        output_dir=(
            "data/processed/"
            "layout"
        ),
        paddle_device="cpu",
    )

    print(
        "Parsing completed."
    )

    for page in document["pages"]:

        print(
            f"\nPage {page['page'] + 1}"
        )

        for block in page["blocks"]:

            print(
                block["final_reading_order"],
                block["type"],
                block.get(
                    "layout_label"
                ),
                repr(
                    block.get(
                        "text",
                        ""
                    )[:100]
                ),
            )