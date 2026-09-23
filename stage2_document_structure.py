import json
import os
import re
from collections import Counter, defaultdict
from statistics import median
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================


WORKING_DIR = Path('E:\HILLUL\Project Associate - I\SDEP\pdf_tree')

INPUT_FILE = WORKING_DIR / "data/processed/layout/reconciled_document.json"

OUTPUT_CLASSIFIED = WORKING_DIR / "data/processed/classified.json"
OUTPUT_READING_ORDER = WORKING_DIR / "data/processed/reading_order.json"
OUTPUT_TREE = WORKING_DIR / "data/processed/document_tree.json"
OUTPUT_MARKDOWN = WORKING_DIR / "data/processed/paper.md"


# ============================================================
# GENERAL UTILITIES
# ============================================================

def clean_text(text):
    if not text:
        return ""

    text = text.replace("\n", " ")
    text = text.replace("\t", " ")

    # Collapse repeated spaces
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_for_comparison(text):
    """
    Used for detecting repeated headers/footers.

    Example:

        "Journal of Food Science | 12"
        "Journal of Food Science | 13"

    should be considered similar.
    """

    text = clean_text(text).lower()

    # Remove page numbers
    text = re.sub(r"\b\d+\b", "", text)

    # Remove excessive punctuation
    text = re.sub(r"[^a-z0-9 ]+", " ", text)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def bbox_height(element):
    bbox = element.get("bbox")

    if not bbox:
        return 0

    return bbox[3] - bbox[1]


def bbox_width(element):
    bbox = element.get("bbox")

    if not bbox:
        return 0

    return bbox[2] - bbox[0]


def y_position(element):
    bbox = element.get("bbox")

    if not bbox:
        return 0

    return bbox[1]


def x_position(element):
    bbox = element.get("bbox")

    if not bbox:
        return 0

    return bbox[0]


# ============================================================
# LOAD JSON
# ============================================================

def load_json(path):

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


def save_json(data, path):

    os.makedirs(
        os.path.dirname(path),
        exist_ok=True
    )

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# NORMALIZE INPUT
# ============================================================

def get_page_number(page):
    """
    Your reconciled JSON uses:
        "page": 5

    Some versions may use:
        "page_number": 5

    Support both.
    """
    return page.get(
        "page_number",
        page.get("page")
    )


def get_element_id(element, page_number, index):
    """
    Support different element ID conventions.
    """

    return (
        element.get("element_id")
        or element.get("id")
        or element.get("block_id")
        or f"P{page_number}_E{index + 1:04d}"
    )


def get_pages(document):
    """
    Handles slightly different possible structures of
    reconciled.json.

    Expected preferred structure:

    {
        "pages": [
            {
                "page_number": 1,
                "width": ...,
                "height": ...,
                "elements": [...]
            }
        ]
    }

    But it also supports pages containing "blocks".
    """

    pages = document.get("pages", [])

    if not pages:
        raise ValueError(
            "No 'pages' found in reconciled.json"
        )

    return pages

def get_element_id(element, page_number, index):
    """
    Support different element ID conventions.
    """

    return (
        element.get("element_id")
        or element.get("id")
        or element.get("block_id")
        or f"P{page_number}_E{index + 1:04d}"
    )

def get_elements_from_page(page):

    if "elements" in page:
        return page["elements"]

    if "blocks" in page:
        return page["blocks"]

    if "paragraphs" in page:
        return page["paragraphs"]

    return []


# ============================================================
# ELEMENT TYPE DETECTION
# ============================================================

KNOWN_HEADINGS = {
    "abstract",
    "introduction",
    "background",
    "materials and methods",
    "materials & methods",
    "methods",
    "methodology",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
    "references",
    "acknowledgements",
    "acknowledgments",
    "abbreviations",
    "data availability",
    "conflict of interest",
    "conflicts of interest",
    "supplementary material",
}


def looks_like_numbered_heading(text):
    """
    Examples:

        1 Introduction
        2. Materials and Methods
        2.1 Fermented foods
        3.2.1 Microbial diversity
    """

    return bool(
        re.match(
            r"^\s*\d+(?:\.\d+)*\.?\s+[A-Z]",
            text
        )
    )


def looks_like_reference(text):
    """
    Conservative reference detection.
    """

    text = clean_text(text)

    if not text:
        return False

    # DOI
    if "doi.org/" in text.lower():
        return True

    # DOI text
    if re.search(
        r"\bdoi\s*:\s*10\.\d+/",
        text.lower()
    ):
        return True

    # Typical journal reference pattern
    if re.search(
        r"\b(19|20)\d{2}\b.*\b\d+\s*\(\d+\)",
        text
    ):
        return True

    return False


def looks_like_caption(text):
    text = clean_text(text)

    if re.match(
        r"^(fig\.?|figure)\s*\d+",
        text,
        re.IGNORECASE
    ):
        return True

    if re.match(
        r"^(table)\s*\d+",
        text,
        re.IGNORECASE
    ):
        return True

    return False


def looks_like_list(text):
    text = clean_text(text)

    return bool(
        re.match(
            r"^([•●▪◦\-–—]|\(?[a-zA-Z0-9]+\)|\d+\.)\s+",
            text
        )
    )


def looks_like_heading(element, page_elements):
    text = clean_text(
        element.get("text", "")
    )

    if not text:
        return False

    lower = text.lower().strip()

    # Known heading
    if lower in KNOWN_HEADINGS:
        return True

    # Numbered heading
    if looks_like_numbered_heading(text):
        return True

    # Very short uppercase heading
    if (
        len(text) <= 100
        and text.upper() == text
        and re.search("[A-Z]", text)
    ):
        return True

    # Explicit metadata
    if element.get("heading") is True:
        return True

    if element.get("type") == "heading":
        return True

    # Font size comparison
    sizes = []

    for e in page_elements:
        size = e.get("font_size")

        if isinstance(size, (int, float)) and size > 0:
            sizes.append(size)

    if sizes:

        typical_size = median(sizes)

        element_size = element.get(
            "font_size",
            0
        )

        if (
            element_size >= typical_size * 1.20
            and len(text) <= 150
        ):
            return True

    # Bold short text
    if (
        element.get("bold") is True
        and len(text) <= 120
        and not text.endswith(".")
    ):
        return True

    return False


# ============================================================
# HEADER / FOOTER DETECTION
# ============================================================

def detect_repeated_header_footer(document):
    """
    Detect repeated text appearing near the top or bottom
    of multiple pages.

    IMPORTANT:

    This does NOT assume that a horizontal line is a header.

    Repetition + position is used as the primary evidence.
    """

    pages = get_pages(document)

    top_candidates = []
    bottom_candidates = []

    for page in pages:

        height = page.get(
            "height",
            1000
        )

        elements = get_elements_from_page(page)

        for element in elements:

            text = clean_text(
                element.get("text", "")
            )

            if not text:
                continue

            y = y_position(element)

            normalized = normalize_for_comparison(
                text
            )

            if not normalized:
                continue

            # Top 10%
            if y < height * 0.10:

                top_candidates.append(
                    (
                        normalized,
                        page.get("page_number"),
                        element
                    )
                )

            # Bottom 10%
            if y > height * 0.90:

                bottom_candidates.append(
                    (
                        normalized,
                        page.get("page_number"),
                        element
                    )
                )

    # Count number of pages containing candidate
    top_page_map = defaultdict(set)
    bottom_page_map = defaultdict(set)

    for normalized, page_number, element in top_candidates:
        top_page_map[normalized].add(
            page_number
        )

    for normalized, page_number, element in bottom_candidates:
        bottom_page_map[normalized].add(
            page_number
        )

    page_count = len(pages)

    # Require repetition on at least 3 pages,
    # or on >= 40% of the document.
    threshold = max(
        3,
        int(page_count * 0.40)
    )

    repeated_headers = {
        text
        for text, pages_found in top_page_map.items()
        if len(pages_found) >= threshold
    }

    repeated_footers = {
        text
        for text, pages_found in bottom_page_map.items()
        if len(pages_found) >= threshold
    }

    return (
        repeated_headers,
        repeated_footers
    )


# ============================================================
# PAGE NUMBER DETECTION
# ============================================================

def looks_like_page_number(text):

    text = clean_text(text)

    if not text:
        return False

    # Simple page number
    if re.fullmatch(
        r"\d+",
        text
    ):
        return True

    # "Page 12"
    if re.fullmatch(
        r"page\s+\d+",
        text,
        re.IGNORECASE
    ):
        return True

    return False


# ============================================================
# CLASSIFY ELEMENT
# ============================================================

def classify_element(
    element,
    page,
    repeated_headers,
    repeated_footers
):

    text = clean_text(
        element.get("text", "")
    )

    if not text:
        return "empty"

    normalized = normalize_for_comparison(
        text
    )

    height = page.get(
        "height",
        1000
    )

    y = y_position(element)

    # --------------------------------------------------------
    # Existing type from reconciliation
    # --------------------------------------------------------

    existing_type = element.get("type")

    if existing_type in {
        "table",
        "figure",
        "image",
        "equation"
    }:

        return existing_type

    # --------------------------------------------------------
    # Repeated header
    # --------------------------------------------------------

    if (
        normalized in repeated_headers
        and y < height * 0.12
    ):

        return "header"

    # --------------------------------------------------------
    # Repeated footer
    # --------------------------------------------------------

    if (
        normalized in repeated_footers
        and y > height * 0.88
    ):

        return "footer"

    # --------------------------------------------------------
    # Page number
    # --------------------------------------------------------

    if (
        looks_like_page_number(text)
        and (
            y < height * 0.15
            or y > height * 0.85
        )
    ):

        return "page_number"

    # --------------------------------------------------------
    # Caption
    # --------------------------------------------------------

    if looks_like_caption(text):

        if re.match(
            r"^(table)\s*\d+",
            text,
            re.IGNORECASE
        ):
            return "table_caption"

        return "figure_caption"

    # --------------------------------------------------------
    # Heading
    # --------------------------------------------------------

    page_elements = get_elements_from_page(
        page
    )

    if looks_like_heading(
        element,
        page_elements
    ):

        return "heading"

    # --------------------------------------------------------
    # Reference
    # --------------------------------------------------------

    if looks_like_reference(text):

        return "reference"

    # --------------------------------------------------------
    # List
    # --------------------------------------------------------

    if looks_like_list(text):

        return "list_item"

    # --------------------------------------------------------
    # Existing paragraph
    # --------------------------------------------------------

    if existing_type == "paragraph":
        return "paragraph"

    # --------------------------------------------------------
    # Default
    # --------------------------------------------------------

    return "paragraph"


# ============================================================
# CLASSIFY WHOLE DOCUMENT
# ============================================================

def classify_document(document):

    headers, footers = detect_repeated_header_footer(
        document
    )

    print(
        "\nDetected repeated headers:"
    )

    for item in headers:
        print("  ", item)

    print(
        "\nDetected repeated footers:"
    )

    for item in footers:
        print("  ", item)

    for page in get_pages(document):

        elements = get_elements_from_page(
            page
        )

        for index, element in enumerate(
            elements
        ):

            # Preserve original element
            element["original_index"] = index

            element["element_id"] = (
                element.get(
                    "element_id"
                )
                or element.get(
                    "block_id"
                )
                or (
                    f"P{page.get('page_number')}"
                    f"_E{index + 1:04d}"
                )
            )

            element["page_number"] = page.get(
                "page_number"
            )

            element["element_type"] = classify_element(
                element,
                page,
                headers,
                footers
            )

            # Header/footer/page-number should not
            # enter scientific reading order
            element["exclude_from_main_text"] = (
                element["element_type"]
                in {
                    "header",
                    "footer",
                    "page_number"
                }
            )

    document["detected_headers"] = list(headers)
    document["detected_footers"] = list(footers)

    return document


# ============================================================
# COLUMN DETECTION
# ============================================================

def detect_page_columns(page):

    elements = [
        e
        for e in get_elements_from_page(page)
        if not e.get(
            "exclude_from_main_text",
            False
        )
    ]

    if len(elements) < 4:
        return 1

    page_width = page.get(
        "width",
        1000
    )

    centers = []

    for element in elements:

        bbox = element.get("bbox")

        if not bbox:
            continue

        width = bbox[2] - bbox[0]

        # Full-width element
        if width > page_width * 0.72:
            continue

        center = (
            bbox[0] + bbox[2]
        ) / 2

        centers.append(center)

    if len(centers) < 4:
        return 1

    centers.sort()

    gaps = [
        centers[i + 1] - centers[i]
        for i in range(
            len(centers) - 1
        )
    ]

    if not gaps:
        return 1

    largest_gap = max(gaps)

    if largest_gap > page_width * 0.18:

        return 2

    return 1


# ============================================================
# ASSIGN COLUMN
# ============================================================

def assign_columns(page):

    column_count = detect_page_columns(
        page
    )

    page["column_count"] = column_count

    page_width = page.get(
        "width",
        1000
    )

    for element in get_elements_from_page(page):

        if element.get(
            "exclude_from_main_text",
            False
        ):
            element["column"] = -1
            continue

        bbox = element.get("bbox")

        if not bbox:

            element["column"] = 0
            continue

        width = bbox[2] - bbox[0]

        if (
            column_count == 2
            and width > page_width * 0.65
        ):

            element["column"] = -1

        elif column_count == 2:

            center = (
                bbox[0] + bbox[2]
            ) / 2

            if center < page_width / 2:
                element["column"] = 0
            else:
                element["column"] = 1

        else:

            element["column"] = 0

    return page


# ============================================================
# READING ORDER
# ============================================================

def calculate_reading_order(page):

    elements = [
        e
        for e in get_elements_from_page(page)
        if not e.get(
            "exclude_from_main_text",
            False
        )
    ]

    if not elements:
        return

    column_count = page.get(
        "column_count",
        1
    )

    # --------------------------------------------------------
    # Single column
    # --------------------------------------------------------

    if column_count == 1:

        ordered = sorted(
            elements,
            key=lambda e: (
                y_position(e),
                x_position(e)
            )
        )

    # --------------------------------------------------------
    # Two columns
    # --------------------------------------------------------

    else:

        full_width = [
            e
            for e in elements
            if e.get("column") == -1
        ]

        left = [
            e
            for e in elements
            if e.get("column") == 0
        ]

        right = [
            e
            for e in elements
            if e.get("column") == 1
        ]

        full_width.sort(
            key=lambda e: (
                y_position(e),
                x_position(e)
            )
        )

        left.sort(
            key=lambda e: (
                y_position(e),
                x_position(e)
            )
        )

        right.sort(
            key=lambda e: (
                y_position(e),
                x_position(e)
            )
        )

        # ----------------------------------------------------
        # Determine whether full-width element is above
        # or below the columns.
        # ----------------------------------------------------

        top_full = []
        bottom_full = []

        for element in full_width:

            if y_position(element) < (
                page.get("height", 1000) * 0.35
            ):
                top_full.append(element)
            else:
                bottom_full.append(element)

        ordered = (
            top_full
            + left
            + right
            + bottom_full
        )

    # --------------------------------------------------------
    # Assign page-local reading order
    # --------------------------------------------------------

    for order, element in enumerate(
        ordered,
        start=1
    ):

        element["page_reading_order"] = order

    page["reading_order"] = [
        e["element_id"]
        for e in ordered
    ]


# ============================================================
# GLOBAL READING ORDER
# ============================================================

def build_global_reading_order(document):

    global_order = 0

    all_elements = []

    for page in get_pages(document):

        calculate_reading_order(page)

        elements = get_elements_from_page(
            page
        )

        ordered = [
            e
            for e in elements
            if not e.get(
                "exclude_from_main_text",
                False
            )
        ]

        ordered.sort(
            key=lambda e: e.get(
                "page_reading_order",
                999999
            )
        )

        for element in ordered:

            global_order += 1

            element["global_reading_order"] = (
                global_order
            )

            all_elements.append(element)

    document["global_reading_order"] = [
        e["element_id"]
        for e in all_elements
    ]

    return document


# ============================================================
# PARAGRAPH CONTINUATION
# ============================================================

def paragraph_continuation_score(
    previous,
    current
):

    score = 0

    previous_text = clean_text(
        previous.get("text", "")
    )

    current_text = clean_text(
        current.get("text", "")
    )

    if not previous_text or not current_text:
        return 0

    # --------------------------------------------------------
    # Same page
    # --------------------------------------------------------

    if (
        previous.get("page_number")
        == current.get("page_number")
    ):
        score += 1

    # --------------------------------------------------------
    # Same column
    # --------------------------------------------------------

    if (
        previous.get("column")
        == current.get("column")
    ):
        score += 4

    # --------------------------------------------------------
    # Similar left alignment
    # --------------------------------------------------------

    if abs(
        x_position(previous)
        - x_position(current)
    ) < 15:

        score += 3

    # --------------------------------------------------------
    # Vertical gap
    # --------------------------------------------------------

    previous_bbox = previous.get("bbox")
    current_bbox = current.get("bbox")

    if previous_bbox and current_bbox:

        gap = (
            current_bbox[1]
            - previous_bbox[3]
        )

        if 0 <= gap <= 25:
            score += 3

        elif 25 < gap <= 45:
            score += 1

    # --------------------------------------------------------
    # Previous sentence incomplete
    # --------------------------------------------------------

    if previous_text.endswith(
        (".", "!", "?", ":", ";")
    ):
        score -= 2

    else:
        score += 2

    # --------------------------------------------------------
    # Current begins lowercase
    # --------------------------------------------------------

    if current_text[0].islower():
        score += 3

    # --------------------------------------------------------
    # Hyphenated continuation
    # --------------------------------------------------------

    if previous_text.endswith("-"):
        score += 5

    # --------------------------------------------------------
    # Heading cannot continue paragraph
    # --------------------------------------------------------

    if current.get(
        "element_type"
    ) == "heading":

        score -= 10

    if previous.get(
        "element_type"
    ) == "heading":

        score -= 10

    return score


# ============================================================
# RECONSTRUCT PARAGRAPHS
# ============================================================

def reconstruct_paragraphs(document):

    for page in get_pages(document):

        page_number = get_page_number(page)

        elements = get_elements_from_page(page)

        elements = [
            e
            for e in elements
            if not e.get(
                "exclude_from_main_text",
                False
            )
        ]

        elements.sort(
            key=lambda e: e.get(
                "page_reading_order",
                e.get(
                    "final_reading_order",
                    e.get(
                        "reading_order",
                        999999
                    )
                )
            )
        )

        paragraphs = []

        current = None

        paragraph_number = 0

        for element in elements:

            element_type = element.get(
                "element_type",
                element.get(
                    "type",
                    "paragraph"
                )
            )

            text = clean_text(
                element.get(
                    "text",
                    element.get(
                        "layout_text",
                        ""
                    )
                )
            )

            if not text:
                continue

            # ------------------------------------------------
            # Non-paragraph elements
            # ------------------------------------------------

            if element_type in {
                "heading",
                "figure",
                "image",
                "figure_caption",
                "table",
                "table_caption",
                "equation"
            }:

                if current:

                    paragraphs.append(
                        current
                    )

                    current = None

                paragraph_id = (
                    f"P{page_number}"
                    f"_PAR{len(paragraphs)+1:04d}"
                )

                paragraphs.append({

                    "paragraph_id": paragraph_id,

                    "type": element_type,

                    "text": text,

                    "page_number": page_number,

                    "column": element.get(
                        "column"
                    ),

                    "source_elements": [
                        get_element_id(
                            element,
                            page_number,
                            len(paragraphs)
                        )
                    ],

                    "bbox": element.get(
                        "bbox"
                    )
                })

                continue

            # ------------------------------------------------
            # First paragraph
            # ------------------------------------------------

            if current is None:

                paragraph_number += 1

                current = {

                    "paragraph_id": (
                        f"P{page_number}"
                        f"_PAR{paragraph_number:04d}"
                    ),

                    "type": "paragraph",

                    "text": text,

                    "page_number": page_number,

                    "column": element.get(
                        "column"
                    ),

                    "source_elements": [
                        get_element_id(
                            element,
                            page_number,
                            paragraph_number
                        )
                    ],

                    "bbox": element.get(
                        "bbox"
                    )
                }

                continue

            # ------------------------------------------------
            # Previous paragraph proxy
            # ------------------------------------------------

            previous_proxy = {

                "text": current["text"],

                "bbox": current["bbox"],

                "page_number": current[
                    "page_number"
                ],

                "column": current[
                    "column"
                ],

                "element_type": "paragraph"
            }

            # ------------------------------------------------
            # Score continuation
            # ------------------------------------------------

            score = paragraph_continuation_score(
                previous_proxy,
                element
            )

            if score >= 5:

                # Hyphenated line/column continuation
                if current["text"].endswith("-"):

                    current["text"] = (
                        current["text"][:-1]
                        + text
                    )

                else:

                    current["text"] = (
                        current["text"]
                        + " "
                        + text
                    )

                current["text"] = clean_text(
                    current["text"]
                )

                current[
                    "source_elements"
                ].append(
                    get_element_id(
                        element,
                        page_number,
                        paragraph_number
                    )
                )

                current["bbox"] = merge_bbox(
                    current["bbox"],
                    element.get("bbox")
                )

            else:

                paragraphs.append(
                    current
                )

                paragraph_number += 1

                current = {

                    "paragraph_id": (
                        f"P{page_number}"
                        f"_PAR{paragraph_number:04d}"
                    ),

                    "type": "paragraph",

                    "text": text,

                    "page_number": page_number,

                    "column": element.get(
                        "column"
                    ),

                    "source_elements": [
                        get_element_id(
                            element,
                            page_number,
                            paragraph_number
                        )
                    ],

                    "bbox": element.get(
                        "bbox"
                    )
                }

        # ----------------------------------------------------
        # Last paragraph on page
        # ----------------------------------------------------

        if current:

            paragraphs.append(
                current
            )

        page["paragraphs"] = paragraphs

    return document


# ============================================================
# BBOX MERGE
# ============================================================

def merge_bbox(b1, b2):

    if not b1:
        return b2

    if not b2:
        return b1

    return [
        min(b1[0], b2[0]),
        min(b1[1], b2[1]),
        max(b1[2], b2[2]),
        max(b1[3], b2[3])
    ]


# ============================================================
# SECTION TREE
# ============================================================

def heading_level(text):

    text = clean_text(text)

    match = re.match(
        r"^\s*(\d+(?:\.\d+)*)\.?\s+",
        text
    )

    if match:

        numbering = match.group(1)

        return numbering.count(".") + 1

    if text.lower() in KNOWN_HEADINGS:

        return 1

    return 1


def build_document_tree(document):

    root = {
        "section_id": "ROOT",
        "title": "Document",
        "level": 0,
        "page_start": None,
        "paragraphs": [],
        "children": []
    }

    stack = [root]

    section_counter = 0

    # Get pages in document order
    pages = get_pages(document)

    for page in pages:

        paragraphs = page.get(
            "paragraphs",
            []
        )

        for paragraph in paragraphs:

            paragraph_type = paragraph.get(
                "type"
            )

            # ------------------------------------------------
            # Heading
            # ------------------------------------------------

            if paragraph_type == "heading":

                section_counter += 1

                title = clean_text(
                    paragraph["text"]
                )

                level = heading_level(
                    title
                )

                section = {
                    "section_id": (
                        f"S{section_counter:03d}"
                    ),
                    "title": title,
                    "level": level,
                    "page_start": paragraph.get(
                        "page_number"
                    ),
                    "paragraphs": [],
                    "children": [],
                    "source_elements": paragraph.get(
                        "source_elements",
                        []
                    )
                }

                # Find correct parent
                while (
                    len(stack) > 1
                    and stack[-1]["level"] >= level
                ):
                    stack.pop()

                stack[-1]["children"].append(
                    section
                )

                stack.append(section)

            # ------------------------------------------------
            # Normal content
            # ------------------------------------------------

            else:

                stack[-1]["paragraphs"].append(
                    paragraph
                )

    return root


# ============================================================
# MARKDOWN
# ============================================================

def markdown_escape(text):

    return text.replace(
        "\n",
        " "
    ).strip()


def tree_to_markdown(
    node,
    lines=None
):

    if lines is None:
        lines = []

    # Root does not get heading
    if node["section_id"] != "ROOT":

        level = max(
            1,
            min(
                node.get("level", 1),
                6
            )
        )

        lines.append(
            "#" * level
            + " "
            + markdown_escape(
                node["title"]
            )
        )

        lines.append("")

    # Content
    for paragraph in node.get(
        "paragraphs",
        []
    ):

        ptype = paragraph.get(
            "type"
        )

        text = markdown_escape(
            paragraph.get(
                "text",
                ""
            )
        )

        if not text:
            continue

        if ptype == "figure_caption":

            lines.append(
                f"*{text}*"
            )

            lines.append("")

        elif ptype == "table_caption":

            lines.append(
                f"**{text}**"
            )

            lines.append("")

        elif ptype == "reference":

            lines.append(
                text
            )

            lines.append("")

        elif ptype == "list_item":

            lines.append(
                text
            )

            lines.append("")

        elif ptype == "table":

            lines.append(
                "<!-- TABLE -->"
            )

            lines.append(text)
            lines.append("")

        elif ptype == "figure":

            lines.append(
                "<!-- FIGURE -->"
            )

            lines.append(text)
            lines.append("")

        else:

            lines.append(text)
            lines.append("")

    # Children
    for child in node.get(
        "children",
        []
    ):

        tree_to_markdown(
            child,
            lines
        )

    return lines


def generate_markdown(tree):

    lines = tree_to_markdown(tree)

    # Remove excessive blank lines
    output = "\n".join(lines)

    output = re.sub(
        r"\n{3,}",
        "\n\n",
        output
    )

    return output.strip() + "\n"


# ============================================================
# CREATE OUTPUT DOCUMENT
# ============================================================

def create_classified_output(document):

    return {
        "source_pdf": document.get(
            "source_pdf"
        ),
        "page_count": document.get(
            "page_count"
        ),
        "stage": "classification",
        "pages": document.get(
            "pages"
        ),
        "detected_headers": document.get(
            "detected_headers",
            []
        ),
        "detected_footers": document.get(
            "detected_footers",
            []
        )
    }


def create_reading_order_output(document):

    elements = []

    for page in get_pages(document):

        for element in get_elements_from_page(
            page
        ):

            if element.get(
                "exclude_from_main_text",
                False
            ):
                continue

            elements.append({
                "element_id": element.get(
                    "element_id"
                ),
                "page_number": element.get(
                    "page_number"
                ),
                "page_reading_order": element.get(
                    "page_reading_order"
                ),
                "global_reading_order": element.get(
                    "global_reading_order"
                ),
                "column": element.get(
                    "column"
                ),
                "element_type": element.get(
                    "element_type"
                ),
                "text": element.get(
                    "text"
                ),
                "bbox": element.get(
                    "bbox"
                )
            })

    elements.sort(
        key=lambda e: e.get(
            "global_reading_order",
            999999
        )
    )

    return {
        "source_pdf": document.get(
            "source_pdf"
        ),
        "elements": elements
    }


# ============================================================
# MAIN PIPELINE
# ============================================================

def main():

    print("=" * 70)
    print("STAGE 2 — DOCUMENT STRUCTURING")
    print("=" * 70)

    # --------------------------------------------------------
    # Load
    # --------------------------------------------------------

    print("\n[1] Loading reconciled.json")

    document = load_json(
        INPUT_FILE
    )

    # --------------------------------------------------------
    # Classification
    # --------------------------------------------------------

    print("\n[2] Classifying elements")

    document = classify_document(
        document
    )

    classified = create_classified_output(
        document
    )

    save_json(
        classified,
        OUTPUT_CLASSIFIED
    )

    print(
        "Saved:",
        OUTPUT_CLASSIFIED
    )

    # --------------------------------------------------------
    # Columns + reading order
    # --------------------------------------------------------

    print("\n[3] Detecting columns")

    for page in get_pages(document):

        assign_columns(page)

    print("\n[4] Building reading order")

    document = build_global_reading_order(
        document
    )

    reading_order = create_reading_order_output(
        document
    )

    save_json(
        reading_order,
        OUTPUT_READING_ORDER
    )

    print(
        "Saved:",
        OUTPUT_READING_ORDER
    )

    # --------------------------------------------------------
    # Paragraph reconstruction
    # --------------------------------------------------------

    print("\n[5] Reconstructing paragraphs")

    document = reconstruct_paragraphs(
        document
    )

    # --------------------------------------------------------
    # Section tree
    # --------------------------------------------------------

    print("\n[6] Building document tree")

    tree = build_document_tree(
        document
    )

    save_json(
        tree,
        OUTPUT_TREE
    )

    print(
        "Saved:",
        OUTPUT_TREE
    )

    # --------------------------------------------------------
    # Markdown
    # --------------------------------------------------------

    print("\n[7] Generating Markdown")

    markdown = generate_markdown(
        tree
    )

    with open(
        OUTPUT_MARKDOWN,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(markdown)

    print(
        "Saved:",
        OUTPUT_MARKDOWN
    )

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    type_counts = Counter()

    total_paragraphs = 0
    total_sections = 0

    for page in get_pages(document):

        for element in get_elements_from_page(
            page
        ):

            type_counts[
                element.get(
                    "element_type",
                    "unknown"
                )
            ] += 1

        total_paragraphs += len(
            page.get(
                "paragraphs",
                []
            )
        )

    def count_sections(node):

        count = 0

        for child in node.get(
            "children",
            []
        ):

            count += 1
            count += count_sections(
                child
            )

        return count

    total_sections = count_sections(
        tree
    )

    print("\n" + "=" * 70)
    print("COMPLETE")
    print("=" * 70)

    print(
        f"Pages       : {len(get_pages(document))}"
    )

    print(
        f"Paragraphs  : {total_paragraphs}"
    )

    print(
        f"Sections    : {total_sections}"
    )

    print("\nElement types:")

    for element_type, count in (
        type_counts.most_common()
    ):

        print(
            f"  {element_type:20s}: {count}"
        )

    print("\nOutput files:")

    print(
        "  ",
        OUTPUT_CLASSIFIED
    )

    print(
        "  ",
        OUTPUT_READING_ORDER
    )

    print(
        "  ",
        OUTPUT_TREE
    )

    print(
        "  ",
        OUTPUT_MARKDOWN
    )


if __name__ == "__main__":
    main()