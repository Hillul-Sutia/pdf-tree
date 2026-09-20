import pymupdf
import json
import re
import os
from statistics import median


# ============================================================
# CONFIGURATION
# ============================================================

file_path = r"E:\HILLUL\Project Associate - I\SDEP\Indigenous fermented foods of Northeast India Emerging opportunities in functional foods, microbiota-driven nutrition and safety perspectives.pdf"


# INPUT_PDF = (
#     "data/raw_pdfs/"
#     "Indigenous fermented foods of Northeast India Emerging opportunities "
#     "in functional foods, microbiota-driven nutrition and safety perspectives.pdf"
# )

INPUT_PDF = file_path 

OUTPUT_DIR = "data/processed"

RAW_JSON = os.path.join(OUTPUT_DIR, "paper_raw.json")
STRUCTURE_JSON = os.path.join(OUTPUT_DIR, "paper_structure.json")
MARKDOWN_FILE = os.path.join(OUTPUT_DIR, "paper.md")


# ============================================================
# BASIC UTILITIES
# ============================================================

def clean_text(text):
    """
    Clean excessive whitespace without removing normal word spaces.
    """

    if not text:
        return ""

    # Convert tabs/newlines to spaces
    text = text.replace("\t", " ")
    text = text.replace("\n", " ")

    # Collapse multiple spaces
    text = re.sub(r"[ ]{2,}", " ", text)

    return text.strip()


def is_bold_span(span):
    """
    PyMuPDF font flags:
    bit 4 generally corresponds to bold.
    Also checks font name as fallback.
    """

    flags = span.get("flags", 0)
    font = span.get("font", "").lower()

    return bool(flags & 16) or "bold" in font


# ============================================================
# STEP 1
# PDF -> RAW BLOCKS USING page.get_text("dict")
# ============================================================

def extract_pdf(pdf_path):
    """
    Extract PDF page -> block -> line -> span structure.

    IMPORTANT:
    We do NOT attempt reading-order reconstruction here.
    """

    doc = pymupdf.open(pdf_path)

    document = {
        "source_pdf": os.path.basename(pdf_path),
        "page_count": len(doc),
        "pages": []
    }

    for page_index, page in enumerate(doc):

        page_dict = page.get_text("dict")

        page_data = {
            "page_number": page_index + 1,
            "width": page.rect.width,
            "height": page.rect.height,
            "blocks": []
        }

        block_counter = 0

        for raw_block in page_dict.get("blocks", []):

            # Ignore image-only blocks at this stage
            if "lines" not in raw_block:
                continue

            block_counter += 1

            lines = []

            for line_index, raw_line in enumerate(
                raw_block.get("lines", [])
            ):

                spans = []

                for span_index, span in enumerate(
                    raw_line.get("spans", [])
                ):

                    spans.append({
                        "span_id": (
                            f"P{page_index + 1}"
                            f"_B{block_counter}"
                            f"_L{line_index + 1}"
                            f"_S{span_index + 1}"
                        ),
                        "text": span.get("text", ""),
                        "bbox": span.get("bbox"),
                        "font": span.get("font", ""),
                        "size": span.get("size", 0),
                        "flags": span.get("flags", 0),
                        "bold": is_bold_span(span)
                    })

                line_text = reconstruct_line(spans)

                if line_text:
                    lines.append({
                        "line_id": (
                            f"P{page_index + 1}"
                            f"_B{block_counter}"
                            f"_L{line_index + 1}"
                        ),
                        "text": line_text,
                        "bbox": raw_line.get("bbox"),
                        "spans": spans
                    })

            if not lines:
                continue

            block_text = " ".join(
                line["text"] for line in lines
            )

            block_text = clean_text(block_text)

            if not block_text:
                continue

            block_bbox = raw_block.get("bbox")

            block_data = {
                "block_id": (
                    f"P{page_index + 1}"
                    f"_B{block_counter}"
                ),
                "page_number": page_index + 1,
                "bbox": block_bbox,
                "text": block_text,
                "lines": lines,

                # Useful metadata
                "font_size": max(
                    (
                        span["size"]
                        for line in lines
                        for span in line["spans"]
                    ),
                    default=0
                ),

                "bold": any(
                    span["bold"]
                    for line in lines
                    for span in line["spans"]
                )
            }

            page_data["blocks"].append(block_data)

        document["pages"].append(page_data)

    doc.close()

    return document


# ============================================================
# STEP 2
# RECONSTRUCT LINE TEXT CORRECTLY
# ============================================================

def reconstruct_line(spans):
    """
    Reconstruct a line from PyMuPDF spans.

    Strategy:

    1. Preserve explicit whitespace spans.
    2. If whitespace is not present between two spans,
       use the x-coordinate gap to decide whether a space
       should be inserted.

    This fixes the "Indigenousfermentedfoodsof..." problem.
    """

    if not spans:
        return ""

    result = ""

    previous_span = None

    for span in spans:

        text = span.get("text", "")

        if text == "":
            continue

        # ----------------------------------------------------
        # First span
        # ----------------------------------------------------

        if previous_span is None:
            result += text
            previous_span = span
            continue

        previous_text = previous_span.get("text", "")

        # ----------------------------------------------------
        # Explicit whitespace already exists
        # ----------------------------------------------------

        if (
            text.startswith(" ")
            or previous_text.endswith(" ")
            or text.isspace()
            or previous_text.isspace()
        ):
            result += text
            previous_span = span
            continue

        # ----------------------------------------------------
        # Fallback: determine space from geometry
        # ----------------------------------------------------

        prev_bbox = previous_span.get("bbox")
        curr_bbox = span.get("bbox")

        if prev_bbox and curr_bbox:

            previous_x1 = prev_bbox[2]
            current_x0 = curr_bbox[0]

            gap = current_x0 - previous_x1

            # Estimate character size
            font_size = max(
                previous_span.get("size", 0),
                span.get("size", 0),
                1
            )

            # Small threshold relative to font size
            threshold = max(0.5, font_size * 0.08)

            if gap > threshold:
                result += " "

        result += text

        previous_span = span

    return clean_text(result)


# ============================================================
# STEP 3
# REPAIR HYPHENATED LINE BREAKS
# ============================================================

def repair_hyphenation(lines):
    """
    Example:

        microor-
        ganisms

    becomes:

        microorganisms

    But:

        community-
        guided

    becomes:

        community-guided

    because the next line begins with a lowercase word and
    the hyphen is treated as a line-break hyphen.

    """

    if not lines:
        return []

    repaired = []

    for line in lines:

        line = clean_text(line)

        if not line:
            continue

        if repaired:

            previous = repaired[-1]

            # Previous line ends with hyphen
            if previous.endswith("-"):

                # Current line begins lowercase
                if line and line[0].islower():

                    # Remove line-break hyphen
                    repaired[-1] = previous[:-1] + line
                    continue

        repaired.append(line)

    return repaired


# ============================================================
# STEP 4
# ADD LINE-LEVEL TEXT REPAIR TO BLOCKS
# ============================================================

def repair_block_text(block):
    """
    Reconstruct block text from its lines and repair
    line-break hyphenation.
    """

    line_texts = [
        line["text"]
        for line in block.get("lines", [])
        if line.get("text")
    ]

    repaired_lines = repair_hyphenation(line_texts)

    block["text"] = clean_text(
        " ".join(repaired_lines)
    )

    return block


def repair_all_blocks(document):
    for page in document["pages"]:
        for block in page["blocks"]:
            repair_block_text(block)

    return document


# ============================================================
# STEP 5
# DETECT COLUMNS
# ============================================================

def detect_columns(page):
    """
    Detect whether a page appears to have one or two columns.

    This is intentionally conservative.

    We do not want images, captions, headers or footers
    to incorrectly define the column structure.
    """

    blocks = page.get("blocks", [])

    if len(blocks) < 4:
        return 1

    page_width = page["width"]

    centers = []

    for block in blocks:

        bbox = block.get("bbox")

        if not bbox:
            continue

        x0, y0, x1, y1 = bbox

        width = x1 - x0

        # Ignore unusually wide blocks
        if width > page_width * 0.75:
            continue

        center = (x0 + x1) / 2

        centers.append(center)

    if len(centers) < 4:
        return 1

    centers_sorted = sorted(centers)

    # Look for a large gap between center clusters
    gaps = []

    for i in range(len(centers_sorted) - 1):
        gaps.append(
            centers_sorted[i + 1] - centers_sorted[i]
        )

    if not gaps:
        return 1

    largest_gap = max(gaps)
    median_gap = median(gaps)

    # A large separation between clusters
    if (
        largest_gap > page_width * 0.18
        and largest_gap > median_gap * 2.5
    ):
        return 2

    return 1


# ============================================================
# STEP 6
# ASSIGN COLUMN TO BLOCK
# ============================================================

def assign_columns(page):
    """
    Assign column = 0 / 1 for two-column pages.

    Wide blocks are treated as full-width blocks.
    """

    blocks = page.get("blocks", [])

    number_of_columns = detect_columns(page)

    page["column_count"] = number_of_columns

    if number_of_columns == 1:

        for block in blocks:
            block["column"] = 0

        return page

    page_width = page["width"]

    for block in blocks:

        bbox = block.get("bbox")

        if not bbox:
            block["column"] = 0
            continue

        x0, y0, x1, y1 = bbox

        width = x1 - x0

        # Full-width element
        if width > page_width * 0.65:

            block["column"] = -1

        else:

            center = (x0 + x1) / 2

            if center < page_width / 2:
                block["column"] = 0
            else:
                block["column"] = 1

    return page


# ============================================================
# STEP 7
# PRELIMINARY READING ORDER
# ============================================================

def sort_page_blocks(page):
    """
    Sort blocks in a two-column scientific paper.

    For two-column pages:

        left column top -> bottom
        right column top -> bottom

    Full-width blocks are handled separately.
    """

    blocks = page.get("blocks", [])

    if page.get("column_count", 1) == 1:

        blocks.sort(
            key=lambda b: (
                b["bbox"][1],
                b["bbox"][0]
            )
        )

        return page

    left = []
    right = []
    full_width = []

    for block in blocks:

        column = block.get("column", 0)

        if column == 0:
            left.append(block)

        elif column == 1:
            right.append(block)

        else:
            full_width.append(block)

    left.sort(
        key=lambda b: (
            b["bbox"][1],
            b["bbox"][0]
        )
    )

    right.sort(
        key=lambda b: (
            b["bbox"][1],
            b["bbox"][0]
        )
    )

    full_width.sort(
        key=lambda b: (
            b["bbox"][1],
            b["bbox"][0]
        )
    )

    # --------------------------------------------------------
    # More robust handling:
    # Full-width blocks near the top are kept first.
    # Then columns.
    # --------------------------------------------------------

    top_full_width = []
    bottom_full_width = []

    if full_width:

        page_height = page["height"]

        for block in full_width:

            y0 = block["bbox"][1]

            if y0 < page_height * 0.25:
                top_full_width.append(block)
            else:
                bottom_full_width.append(block)

    ordered = (
        top_full_width
        + left
        + right
        + bottom_full_width
    )

    page["blocks"] = ordered

    return page


# ============================================================
# STEP 8
# DETECT HEADINGS
# ============================================================

COMMON_HEADINGS = {
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
    "supplementary material",
    "data availability",
    "conflict of interest",
    "conflicts of interest"
}


def looks_like_heading(block, page_blocks):
    """
    Heuristic heading detector.

    This is not expected to be perfect.
    """

    text = clean_text(block.get("text", ""))

    if not text:
        return False

    lower = text.lower().strip()

    # --------------------------------------------------------
    # Known scientific-paper headings
    # --------------------------------------------------------

    if lower in COMMON_HEADINGS:
        return True

    # --------------------------------------------------------
    # Numbered headings
    #
    # Examples:
    # 1 Introduction
    # 2.1 Fermentation process
    # 3.2.1 Microbial diversity
    # --------------------------------------------------------

    if re.match(
        r"^\d+(\.\d+)*\.?\s+[A-Z]",
        text
    ):
        return True

    # --------------------------------------------------------
    # Short all-uppercase headings
    # --------------------------------------------------------

    if (
        len(text) < 100
        and text.upper() == text
        and re.search(r"[A-Z]", text)
    ):
        return True

    # --------------------------------------------------------
    # Font-based heuristic
    # --------------------------------------------------------

    font_sizes = [
        b.get("font_size", 0)
        for b in page_blocks
        if b.get("font_size", 0) > 0
    ]

    if font_sizes:

        typical_size = median(font_sizes)

        if (
            block.get("font_size", 0)
            >= typical_size * 1.18
            and len(text) < 150
        ):
            return True

    # --------------------------------------------------------
    # Bold short text
    # --------------------------------------------------------

    if (
        block.get("bold")
        and len(text) < 120
        and not text.endswith(".")
    ):
        return True

    return False


# ============================================================
# STEP 9
# PARAGRAPH CONTINUATION SCORE
# ============================================================

def continuation_score(previous, current):
    """
    Estimate whether two blocks belong to the same paragraph.

    Higher score = more likely continuation.
    """

    score = 0

    prev_bbox = previous.get("bbox")
    curr_bbox = current.get("bbox")

    if not prev_bbox or not curr_bbox:
        return 0

    prev_x0, prev_y0, prev_x1, prev_y1 = prev_bbox
    curr_x0, curr_y0, curr_x1, curr_y1 = curr_bbox

    # --------------------------------------------------------
    # Same page
    # --------------------------------------------------------

    if previous.get("page_number") == current.get("page_number"):
        score += 1

    # --------------------------------------------------------
    # Same column
    # --------------------------------------------------------

    if previous.get("column") == current.get("column"):
        score += 4

    # --------------------------------------------------------
    # Vertical relationship
    # --------------------------------------------------------

    vertical_gap = curr_y0 - prev_y1

    if 0 <= vertical_gap <= 25:
        score += 3

    elif 25 < vertical_gap <= 45:
        score += 1

    # --------------------------------------------------------
    # Similar left position
    # --------------------------------------------------------

    if abs(prev_x0 - curr_x0) < 15:
        score += 3

    # --------------------------------------------------------
    # Previous text does not end like a completed sentence
    # --------------------------------------------------------

    prev_text = previous.get("text", "").strip()
    curr_text = current.get("text", "").strip()

    if prev_text:

        if prev_text.endswith(
            (".", "!", "?", ":", ";")
        ):
            score -= 2

        else:
            score += 2

    # --------------------------------------------------------
    # Current starts with lowercase
    # --------------------------------------------------------

    if curr_text and curr_text[0].islower():
        score += 3

    # --------------------------------------------------------
    # Current starts with punctuation
    # --------------------------------------------------------

    if curr_text.startswith(
        (",", ".", ";", ":", ")", "]", "%")
    ):
        score += 2

    # --------------------------------------------------------
    # Current looks like a heading
    # --------------------------------------------------------

    if looks_like_heading(
        current,
        [current]
    ):
        score -= 8

    return score


# ============================================================
# STEP 10
# RECONSTRUCT PARAGRAPHS
# ============================================================

def reconstruct_paragraphs(page):
    """
    Convert layout blocks into paragraphs.
    """

    blocks = page.get("blocks", [])

    paragraphs = []

    current_paragraph = None

    paragraph_counter = 0

    for block in blocks:

        text = clean_text(block.get("text", ""))

        if not text:
            continue

        # ----------------------------------------------------
        # Heading blocks always start a new element
        # ----------------------------------------------------

        is_heading = looks_like_heading(
            block,
            blocks
        )

        if is_heading:

            if current_paragraph:

                paragraphs.append(current_paragraph)
                current_paragraph = None

            paragraph_counter += 1

            paragraphs.append({
                "paragraph_id": (
                    f"P{page['page_number']}"
                    f"_PAR{paragraph_counter}"
                ),
                "type": "heading",
                "page_number": page["page_number"],
                "column": block.get("column"),
                "text": text,
                "source_blocks": [
                    block["block_id"]
                ],
                "bbox": block["bbox"]
            })

            continue

        # ----------------------------------------------------
        # First normal paragraph
        # ----------------------------------------------------

        if current_paragraph is None:

            paragraph_counter += 1

            current_paragraph = {
                "paragraph_id": (
                    f"P{page['page_number']}"
                    f"_PAR{paragraph_counter}"
                ),
                "type": "paragraph",
                "page_number": page["page_number"],
                "column": block.get("column"),
                "text": text,
                "source_blocks": [
                    block["block_id"]
                ],
                "bbox": block["bbox"]
            }

            continue

        # ----------------------------------------------------
        # Check continuation
        # ----------------------------------------------------

        previous_block = {
            "bbox": current_paragraph["bbox"],
            "text": current_paragraph["text"],
            "page_number": current_paragraph["page_number"],
            "column": current_paragraph["column"]
        }

        score = continuation_score(
            previous_block,
            block
        )

        # ----------------------------------------------------
        # Continue paragraph
        # ----------------------------------------------------

        if score >= 5:

            # If previous text ends with a hyphen,
            # join without inserting a space.
            if current_paragraph["text"].endswith("-"):

                current_paragraph["text"] = (
                    current_paragraph["text"][:-1]
                    + text
                )

            else:

                current_paragraph["text"] = (
                    current_paragraph["text"]
                    + " "
                    + text
                )

            current_paragraph["text"] = clean_text(
                current_paragraph["text"]
            )

            current_paragraph["source_blocks"].append(
                block["block_id"]
            )

            # Expand bounding box
            current_paragraph["bbox"] = merge_bbox(
                current_paragraph["bbox"],
                block["bbox"]
            )

        # ----------------------------------------------------
        # New paragraph
        # ----------------------------------------------------

        else:

            paragraphs.append(current_paragraph)

            paragraph_counter += 1

            current_paragraph = {
                "paragraph_id": (
                    f"P{page['page_number']}"
                    f"_PAR{paragraph_counter}"
                ),
                "type": "paragraph",
                "page_number": page["page_number"],
                "column": block.get("column"),
                "text": text,
                "source_blocks": [
                    block["block_id"]
                ],
                "bbox": block["bbox"]
            }

    # --------------------------------------------------------
    # Add final paragraph
    # --------------------------------------------------------

    if current_paragraph:
        paragraphs.append(current_paragraph)

    page["paragraphs"] = paragraphs

    return page


# ============================================================
# BBOX UTILITY
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
# STEP 11
# PROCESS ALL PAGES
# ============================================================

def process_document(document):

    for page in document["pages"]:

        # Detect columns
        assign_columns(page)

        # Determine reading order
        sort_page_blocks(page)

        # Reconstruct paragraphs
        reconstruct_paragraphs(page)

    return document


# ============================================================
# STEP 12
# BUILD DOCUMENT ELEMENT LIST
# ============================================================

def collect_elements(document):

    elements = []

    for page in document["pages"]:

        for paragraph in page.get(
            "paragraphs",
            []
        ):

            element = paragraph.copy()

            element["page_number"] = page[
                "page_number"
            ]

            elements.append(element)

    return elements


# ============================================================
# STEP 13
# BUILD SECTION TREE
# ============================================================

def get_heading_level(text):

    text = clean_text(text)

    # --------------------------------------------------------
    # Numbered heading
    # --------------------------------------------------------

    match = re.match(
        r"^(\d+(?:\.\d+)*)\.?\s+",
        text
    )

    if match:

        numbering = match.group(1)

        return numbering.count(".") + 1

    # --------------------------------------------------------
    # Major known headings
    # --------------------------------------------------------

    if text.lower() in COMMON_HEADINGS:
        return 1

    return 1


def build_section_tree(document):

    elements = collect_elements(document)

    root = {
        "section_id": "ROOT",
        "title": "Document",
        "level": 0,
        "children": [],
        "paragraphs": []
    }

    stack = [root]

    section_counter = 0

    for element in elements:

        if element["type"] == "heading":

            section_counter += 1

            level = get_heading_level(
                element["text"]
            )

            section = {
                "section_id": (
                    f"S{section_counter:03d}"
                ),
                "title": element["text"],
                "level": level,
                "page_number": element[
                    "page_number"
                ],
                "children": [],
                "paragraphs": [],
                "source_blocks": element[
                    "source_blocks"
                ]
            }

            # Find parent section
            while (
                len(stack) > 1
                and stack[-1]["level"] >= level
            ):
                stack.pop()

            stack[-1]["children"].append(
                section
            )

            stack.append(section)

        else:

            # Add paragraph to current section
            stack[-1]["paragraphs"].append(
                element
            )

    return root


# ============================================================
# STEP 14
# MARKDOWN GENERATION
# ============================================================

def markdown_from_tree(node, level=0):

    lines = []

    # Root doesn't need a heading
    if node["section_id"] != "ROOT":

        heading_level = min(
            max(node["level"], 1),
            6
        )

        lines.append(
            "#" * heading_level
            + " "
            + node["title"]
        )

        lines.append("")

    # Paragraphs
    for paragraph in node.get(
        "paragraphs",
        []
    ):

        text = clean_text(
            paragraph.get("text", "")
        )

        if text:

            lines.append(text)
            lines.append("")

    # Child sections
    for child in node.get(
        "children",
        []
    ):

        lines.extend(
            markdown_from_tree(
                child,
                level + 1
            )
        )

    return lines


def generate_markdown(tree):

    lines = markdown_from_tree(tree)

    return "\n".join(lines).strip() + "\n"


# ============================================================
# STEP 15
# SAVE JSON
# ============================================================

def save_json(data, path):

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
# MAIN
# ============================================================

def main():

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    print("Reading PDF:")
    print(INPUT_PDF)

    # --------------------------------------------------------
    # STEP 1
    # Raw extraction
    # --------------------------------------------------------

    print("\n[1/6] Extracting PDF layout...")

    document = extract_pdf(
        INPUT_PDF
    )

    save_json(
        document,
        RAW_JSON
    )

    print(
        f"Saved raw extraction: {RAW_JSON}"
    )

    # --------------------------------------------------------
    # STEP 2
    # Repair text
    # --------------------------------------------------------

    print(
        "\n[2/6] Repairing text and hyphenation..."
    )

    document = repair_all_blocks(
        document
    )

    # --------------------------------------------------------
    # STEP 3
    # Reading order + paragraphs
    # --------------------------------------------------------

    print(
        "\n[3/6] Reconstructing reading order..."
    )

    document = process_document(
        document
    )

    # --------------------------------------------------------
    # STEP 4
    # Section tree
    # --------------------------------------------------------

    print(
        "\n[4/6] Building section tree..."
    )

    section_tree = build_section_tree(
        document
    )

    # --------------------------------------------------------
    # STEP 5
    # Structured output
    # --------------------------------------------------------

    structure = {
        "source_pdf": document[
            "source_pdf"
        ],
        "page_count": document[
            "page_count"
        ],
        "pages": document[
            "pages"
        ],
        "section_tree": section_tree
    }

    save_json(
        structure,
        STRUCTURE_JSON
    )

    print(
        f"Saved structure: {STRUCTURE_JSON}"
    )

    # --------------------------------------------------------
    # STEP 6
    # Markdown
    # --------------------------------------------------------

    print(
        "\n[5/6] Generating Markdown..."
    )

    markdown = generate_markdown(
        section_tree
    )

    with open(
        MARKDOWN_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(markdown)

    print(
        f"Saved Markdown: {MARKDOWN_FILE}"
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    total_blocks = sum(
        len(page["blocks"])
        for page in document["pages"]
    )

    total_paragraphs = sum(
        len(page.get("paragraphs", []))
        for page in document["pages"]
    )

    print("\n[6/6] COMPLETE")
    print("--------------------------------")
    print(
        f"Pages       : {document['page_count']}"
    )
    print(
        f"Blocks      : {total_blocks}"
    )
    print(
        f"Paragraphs  : {total_paragraphs}"
    )
    print(
        f"Raw JSON    : {RAW_JSON}"
    )
    print(
        f"Structure   : {STRUCTURE_JSON}"
    )
    print(
        f"Markdown    : {MARKDOWN_FILE}"
    )
    print("--------------------------------")


if __name__ == "__main__":
    main()