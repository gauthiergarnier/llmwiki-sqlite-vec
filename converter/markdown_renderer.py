"""Renders untrusted opendataloader JSON elements as markdown under strict bounds."""

from converter.config import ConverterConfig
from converter.text_budget import TextBudget


class MarkdownRenderer:
    def __init__(self, config: ConverterConfig) -> None:
        self._config = config

    def render(self, el: dict) -> str:
        """Convert a single JSON element to markdown under a fresh per-element text budget."""
        return self._render(el, TextBudget(self._config.max_element_text_bytes), 0)

    def _render(self, el: dict, budget: TextBudget, depth: int) -> str:
        if not isinstance(el, dict):
            raise RuntimeError("opendataloader elements must be objects")
        element_type = el.get("type", "")
        if not isinstance(element_type, str):
            raise RuntimeError("opendataloader element type must be text")

        if element_type == "heading":
            return self._render_heading(el, budget)
        if element_type == "paragraph":
            return budget.take(el.get("content", ""), "paragraph text")
        if element_type == "list":
            return self._render_list(el, budget)
        if element_type == "table":
            return self._render_table(el, budget, depth)
        if element_type == "text block":
            return self._render_text_block(el, budget, depth)
        if element_type == "image":
            src = budget.take(el.get("source", ""), "image source", 10)
            return f"![image]({src})" if src else ""
        if element_type == "caption":
            content = budget.take(el.get("content", ""), "caption text", 2)
            return f"*{content}*" if content else ""
        return ""

    def _render_heading(self, el: dict, budget: TextBudget) -> str:
        raw_level = el.get("heading level", 1)
        level = max(1, min(raw_level, 6)) if type(raw_level) is int else 1
        content = budget.take(el.get("content", ""), "heading text", level + 1)
        return f"{'#' * level} {content}"

    def _render_list(self, el: dict, budget: TextBudget) -> str:
        items = el.get("list items", [])
        if not isinstance(items, list):
            raise RuntimeError("opendataloader list items must be a list")
        self._check_child_count(len(items))

        lines: list[str] = []
        child_count = len(items)
        for item in items:
            if not isinstance(item, dict):
                raise RuntimeError("opendataloader list items must be objects")
            item_content = budget.take(item.get("content", ""), "list item text", 2 + bool(lines))
            lines.append(f"- {item_content}")
            children = item.get("kids", [])
            if not isinstance(children, list):
                raise RuntimeError("opendataloader list children must be a list")
            child_count += len(children)
            self._check_child_count(child_count)
            for child in children:
                if not isinstance(child, dict):
                    raise RuntimeError("opendataloader list children must be objects")
                child_content = budget.take(child.get("content", ""), "list child text", 4 + bool(lines))
                lines.append(f"  - {child_content}")
        return "\n".join(lines)

    def _render_table(self, el: dict, budget: TextBudget, depth: int) -> str:
        """Render a table element as a markdown table, treating row one as the header."""
        rows = el.get("rows", [])
        if not isinstance(rows, list):
            raise RuntimeError("opendataloader table rows must be a list")
        self._check_child_count(len(rows))

        grid = []
        cell_count = 0
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError("opendataloader table rows must be objects")
            cells = row.get("cells", [])
            if not isinstance(cells, list):
                raise RuntimeError("opendataloader table cells must be a list")
            cell_count += len(cells)
            self._check_child_count(cell_count)
            rendered = [
                self._escape_cell(self._inline_cell_text(cell, budget, depth + 1))
                for cell in cells
            ]
            if rendered:
                grid.append(rendered)

        if not any(any(cell for cell in row) for row in grid):
            return ""

        width = max(len(row) for row in grid)
        padded = [row + [""] * (width - len(row)) for row in grid]
        header, body = padded[0], padded[1:]

        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        lines.extend("| " + " | ".join(row) + " |" for row in body)
        return "\n".join(lines)

    def _inline_cell_text(self, cell: dict, budget: TextBudget, depth: int) -> str:
        """Flatten a table cell's nested blocks into single-line text."""
        if depth > self._config.max_element_depth:
            return ""
        if not isinstance(cell, dict):
            raise RuntimeError("opendataloader table cells must be objects")

        parts = []
        content = cell.get("content")
        if content is not None:
            text = budget.take(content, "table cell text").strip()
            if text:
                parts.append(text)

        kids = cell.get("kids", [])
        if not isinstance(kids, list):
            raise RuntimeError("opendataloader table cell kids must be a list")
        self._check_child_count(len(kids))

        for kid in kids:
            nested = self._inline_cell_text(kid, budget, depth + 1)
            if nested:
                parts.append(nested)
        return " ".join(parts)

    def _render_text_block(self, el: dict, budget: TextBudget, depth: int) -> str:
        if depth > self._config.max_element_depth:
            return ""
        kids = el.get("kids", [])
        if not isinstance(kids, list):
            raise RuntimeError("opendataloader text block kids must be a list")
        self._check_child_count(len(kids))

        parts = []
        for kid in kids:
            md = self._render(kid, budget, depth + 1)
            if md:
                parts.append(md)
        return "\n\n".join(parts)

    def _check_child_count(self, count: int) -> None:
        if count > self._config.max_element_children:
            raise RuntimeError("opendataloader element has too many children")

    @staticmethod
    def _escape_cell(text: str) -> str:
        return text.replace("|", "\\|").replace("\n", " ").strip()
