import re

from converter.ast_parser import parse_edxml_to_ast
from converter.ast_renderer_md import ast_to_markdown


def shift_markdown_headings(md: str, offset: int = 1) -> str:
    """
    Shift all Markdown heading levels down by `offset` levels.
    """

    def _repl(match: re.Match) -> str:
        hashes = match.group(1)
        text = match.group(2)
        new_level = min(len(hashes) + offset, 6)
        return "#" * new_level + " " + text

    return re.sub(r"^(#{1,6})\s+(.*)$", _repl, md, flags=re.MULTILINE)


def edxml_to_markdown(xml: str) -> str:
    """
    Convert raw EdXML to Markdown via the shared AST pipeline.
    """
    node = parse_edxml_to_ast(xml)
    return ast_to_markdown(node)
