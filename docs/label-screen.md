# Label screen

The label screen is a small web app for reviewing and extending the gold labels in
`evals/gold/`. Nothing is written until you press Save. The server then checks the whole
document against the gold schema and writes the JSON file in place, so every change is an
ordinary `git diff` to review and commit.

![The label screen with CTC-01 open](img/label-screen/overview.png)

## Start it

```sh
(cd src/ui && npm ci && npm run build)
uv run resourcly ui   # http://127.0.0.1:8000
```

| Option | What it does |
| --- | --- |
| `--port 8001` | Serve on another port. |
| `--gold-dir <dir>` or `RESOURCLY_GOLD_DIR=<dir>` | Read and write gold in another folder, for example a copy to try edits on. |

## Work on a drawing

| To do this | Do this |
| --- | --- |
| Open a drawing | Pick it in the Drawing list at the top. Each entry shows how many values are approved. |
| Change page | Use the page arrows next to the counts. |
| Open a value | Click its numbered box on the page, or its row in the list. |
| Edit a value | Change any field in the form. Drag the box, or its corners, to move or resize it. |
| Add a value | Drag a box on the page. A new value opens in the form. |
| Approve a value | Press `A` or click Approve. The status changes from `draft` to `approved`. |
| Edit features | Open the Features tab: id, type, label, description and page of each feature. |
| Edit the title block | Open the Title block tab: title, revision, units and the other sheet fields. |
| Look without editing | Turn on Demo. Saving and approving are switched off. |

![A value open in the form](img/label-screen/editing.png)

## Keys

| Key | Action |
| --- | --- |
| `J` / `K` | Next or previous value |
| `A` | Approve the open value (again to set it back to draft) |
| `Cmd+S` / `Ctrl+S` | Save |
| `Esc` | Close the open value |
| Space + drag | Pan the page |
| Ctrl + scroll | Zoom |

## How saving works

| Step | What happens |
| --- | --- |
| While you edit | The screen sends the document to the server's check, and each issue shows next to its field. The header counts them. |
| Save | The server validates the whole document against the gold models. If it is invalid, nothing is written and the issues are listed. |
| Write | The server writes a temporary file and then replaces the old one, so a crash never leaves a half-written file. The file stays in `evals/gold/drawings/` or `evals/gold/partial/`; a drawing with no gold yet gets a new file in `drawings/`. |
| Review | The change is a normal git diff. Review it, then commit it. |

![A unit that does not fit the value, shown as an issue](img/label-screen/issue.png)

Partial gold drawings open the same way. They hold about ten values each, so most callouts on
the page have no box.

![A partial gold drawing on page 2](img/label-screen/partial.png)

The screen has a light theme only.
