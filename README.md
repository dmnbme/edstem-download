# Ed Lessons Download Tool

A small but powerful tool for downloading Ed lessons (slides) from edstem.org and save as clean Markdown files, in clear, well-structured directories.

It preserves as much of the original slide content as possible, including code snippets, HTML widgets, spoilers, and embedded assets.

## Supported content

| Original content                                             | Output using             |
| ------------------------------------------------------------ | ------------------------ |
| - Bold / Italic / Strikethrough text<br />- Inline code / Code block<br />- List<br />- Link without styles<br />- Quote block<br />- Heading | Native Markdown          |
| - Underlined text<br />- Spoiler<br />- Link with styles     | HTML                     |
| - Image                                                      | Base64-encoded in HTML   |
| - Admonition                                                 | GItHub Flavored Markdown |
| - Web snippet                                                | iframe in HTML           |

## Dependencies



## Usage

1. Create an API token on Ed settings page
2. Set the API token in `config.toml` or environment variable `ED_PAT`
3. 

## Disclaimer

- Please obtain permission from your course staff before using this tool
- This project is not affiliated with Edstem.org