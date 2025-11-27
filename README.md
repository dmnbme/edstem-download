# Ed Lessons Download Tool

A small but powerful tool for downloading Ed lessons (slides) from edstem.org and save as clean Markdown files, in clear, well-structured directories.

It preserves as much of the original slide content as possible, including code snippets, HTML widgets, spoilers, and embedded assets.

**Copyright warning: Please obtain permission from your course staff before using this tool.**

## Supported content

| Original content                                             | Output using                                     |
| ------------------------------------------------------------ | ------------------------------------------------ |
| - Bold / Italic / Strikethrough text<br />- Inline code / Code block<br />- List<br />- Link<br />- Quote block<br />- Heading | Native Markdown                                  |
| - Underlined text<br />- Spoiler                             | HTML                                             |
| - Image                                                      | Base64-encoded in HTML with preserved dimensions |
| - Admonition                                                 | Extended Markdown (GFM)                          |
| - Web snippet                                                | iframe in HTML                                   |

## Usage

