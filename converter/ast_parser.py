import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Node:
    """
    Lightweight AST node representing the Ed XML structure.
    `kind` distinguishes text nodes from element nodes so that
    text order (including tails) is preserved.
    """

    kind: str  # "element" or "text"
    tag: Optional[str] = None
    attrs: Dict[str, str] = field(default_factory=dict)
    children: List["Node"] = field(default_factory=list)
    text: str = ""


def _elem_to_node(elem: ET.Element) -> Node:
    children: List[Node] = []

    if elem.text:
        children.append(Node(kind="text", text=elem.text))

    for child in elem:
        children.append(_elem_to_node(child))
        if child.tail:
            children.append(Node(kind="text", text=child.tail))

    return Node(
        kind="element",
        tag=elem.tag.lower(),
        attrs={k.lower(): v for k, v in elem.attrib.items()},
        children=children,
    )


def parse_edxml_to_ast(xml: str) -> Node:
    """
    Parse Ed XML into a normalized AST that preserves ordering.
    Falls back to wrapping fragments in a root <document>.
    """
    if not xml:
        return Node(kind="element", tag="document")

    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        wrapped = f"<document>{xml}</document>"
        root = ET.fromstring(wrapped)

    return _elem_to_node(root)
