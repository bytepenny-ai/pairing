"""Cleans a PDF's page texts before they are chunked and embedded (document_extract.extract_text).

PDF text keeps the page layout: lines wrapped where the page ended them, bullet and decoration marks, and the same
header or footer (with a page number) on every page. These make passages noisier and their search scores lower."""

import re
from collections import Counter

_HAS_WORD = re.compile(r"\w")
_BULLET = re.compile(r"^[^\w\s]{1,3}\s+")  # a mark of 1 to 3 symbols, then a space: "> ", "$ ", "- ", "• "
_DIGITS = re.compile(r"\d+")
_WRAPPED_WORD = re.compile(r"\w-$")  # a word or link split over two lines at a hyphen
_REPEATED_MIN_PAGES = 3  # an edge line on at least this many pages, and on half of them, is a header or footer
_EDGE_LINES = 2  # header and footer lines: this many at the top and bottom of a page
_REPEATED_MAX_LENGTH = 80


class PdfText:
    def __init__(self, pages: list[str]) -> None:
        self._pages = [[line.strip() for line in page.splitlines()] for page in pages]

    def text(self) -> str:
        """The pages as clean paragraphs, one blank line between pages."""
        repeated = self._repeated_lines()
        pages = (self._page(lines, repeated) for lines in self._pages)
        return "\n\n".join(page for page in pages if page)

    def _repeated_lines(self) -> set[str]:
        """Top or bottom lines found on many pages once numbers are ignored, such as "Company 3 / 8"; a title in the
        page body ("Step 1", "Step 2") stays."""
        if len(self._pages) < _REPEATED_MIN_PAGES:
            return set()
        pages_with: Counter[str] = Counter()
        for lines in self._pages:
            filled = [line for line in lines if line and len(line) <= _REPEATED_MAX_LENGTH]
            pages_with.update({self._shape(line) for line in filled[:_EDGE_LINES] + filled[-_EDGE_LINES:]})
        needed = max(_REPEATED_MIN_PAGES, len(self._pages) / 2)
        return {shape for shape, count in pages_with.items() if count >= needed}

    def _page(self, lines: list[str], repeated: set[str]) -> str:
        """One page: decoration and repeated lines dropped, bullet marks removed, wrapped lines joined. A line that
        had a bullet mark starts a new line; any other line continues the one before."""
        out: list[str] = []
        filled = [index for index, line in enumerate(lines) if line]
        edges = set(filled[:_EDGE_LINES] + filled[-_EDGE_LINES:])
        for index, line in enumerate(lines):
            if not _HAS_WORD.search(line) or (index in edges and self._shape(line) in repeated):
                if not line and out and out[-1]:
                    out.append("")  # a blank line keeps the paragraph break
                continue
            bare = _BULLET.sub("", line)
            if out and out[-1] and bare == line:
                out[-1] += ("" if _WRAPPED_WORD.search(out[-1]) else " ") + line
            else:
                out.append(bare)
        return "\n".join(out).strip()

    @staticmethod
    def _shape(line: str) -> str:
        return _DIGITS.sub("#", line.lower())
