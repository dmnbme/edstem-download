# Ed Lessons Download Tool

A small but powerful tool for downloading Ed lessons (slides) from edstem.org and save as clean Markdown files, in clear, well-structured directories.

It preserves as much of the original slide content as possible, including admonitions, code snippets, HTML widgets, spoilers, and embedded assets.

## Features

**This project addresses these problems of downloading from Ed:**

- PDF download of lessons not including PDF-type or other filetype slides
- Repetitive clicking of download PDF / code workspace files
- Messy format when downloading with non-Chromium browsers

**This project provides:**

- One-click download of all your Ed lessons
- Well-formatted markdown files
- As much of the original slide content as possible

## Supported content

| Original content                                             | Output using                                                 |
| ------------------------------------------------------------ | ------------------------------------------------------------ |
| Bold / Italic / Strikethrough text<br />Inline code / Code block<br />List<br />Link without styles<br />Quote block<br />Heading | Native Markdown                                              |
| Underlined text<br />Spoiler<br />Link with styles           | HTML                                                         |
| Image                                                        | Base64-encoded in HTML<br />Files stored in separate folders |
| Admonition                                                   | GItHub Flavored Markdown                                     |
| Web snippet                                                  | iframe in HTML                                               |

In short, everything from [here](https://edstem.org/help/content-editor) except Polls.

## Prerequisites

- Python ≥ 3.11
- Pandoc (must be installed and available in PATH)

## Usage

1. Make sure you met all the prerequisites

2. Create an API token on Ed settings page

3. Set the API token in `config.toml` or in environment variable `ED_PAT`

4. Clone the repository and run from file

   ```shell
   # Clone the repository
   git clone https://github.com/dmnbme/edstem-download
   cd edstem-download
   
   # Install dependencies
   pip install -r requirements.txt
   
   # Run from file
   python main.py
   ```


## To-do

- [ ] Lesson feedback comment
- [ ] Workspace files download
- [ ] Polls supported
- [ ] Export to more formats ( rtf / pdf / ... )
- [ ] Export to other platforms ( Notion / )
- [ ] Parallel downloads
- [ ] Resumable downloads
- [ ] Better progress bar

## Disclaimer

- Please obtain permission from your course staff before using this tool
- This project is not affiliated with Edstem.org