# Building the printable handbook

The Markdown guides are the maintained source and the authoritative copyable commands. `docs/MBS_Complete_Handbook.pdf` combines the index, feature/use-case catalogue, employee/staff guides, HTTP deployment, operations, troubleshooting, architecture, database design, laptop README and verification evidence. The alternative HTTPS guide remains linked separately.

The optional builder uses ReportLab and does not change the application's runtime dependencies. From the repository, with a local Python 3.12 installation:

```powershell
python -m venv .venv-docs
.\.venv-docs\Scripts\python.exe -m pip install -r requirements-docs.txt
.\.venv-docs\Scripts\python.exe docs/build_handbook.py
```

Linux equivalent:

```bash
python3 -m venv .venv-docs
.venv-docs/bin/python -m pip install -r requirements-docs.txt
.venv-docs/bin/python docs/build_handbook.py
```

Do not run this inside the read-only production web container. Build on a developer laptop/approved documentation machine, review the result, then commit it with the updated guides. The builder uses installed Times New Roman/Consolas on Windows or standard PDF Times/Courier fonts elsewhere; it does not redistribute font files. Python must have access to the source repository.

Custom output path:

```bash
python docs/build_handbook.py --output output/pdf/MBS_Complete_Handbook.pdf
```

The PDF includes clickable contents/bookmarks, linked source references, repeated table headers, component/relationship diagrams and wrapped command displays. Wraps are for reading; use full source command blocks when executing. Simplified diagrams complement the full Mermaid source and schema tables.

After behavior changes, review all affected guides and update the handbook review date/application baseline in the builder before regenerating. Verify Markdown links and command syntax; render the PDF to pages with `pdftoppm` if available and inspect cover, contents, tables, commands, diagrams and final pages. Check that no text clips or missing glyphs appear and no secret/personal test recipient entered the guides. Documentation review does not require running commands that send mail, change accounts or restore production data.

Commit the Markdown and PDF together to `mbs-prod`. Documentation-only updates require a Git pull on the server to read the files, with no image rebuild or service restart.
