# Lesson Plan Generator (Streamlit)

Upload a syllabus PDF, parse weekly items, generate/edit a weekly lesson-plan report draft, and export as TXT or fixed-layout PDF.

## Files
- `web_app.py`: Streamlit UI + persistent syllabus library.
- `lessonplan_bot.py`: syllabus PDF parsing + weekly draft generation.
- `pdf_template.py`: fixed-layout PDF template rendering using `fpdf2`.
- `data/syllabi/`: persisted uploaded files.
- `data/syllabi_index.json`: persisted index + parsed week metadata.

## Run locally
```bash
pip install -r requirements.txt
streamlit run web_app.py
```

## Streamlit Cloud deployment
1. Push this repo as-is.
2. Ensure `requirements.txt` exists at repo root (already included).
3. Keep `packages.txt` at repo root so apt can install Korean fonts (`fonts-nanum`) for PDF rendering.
4. Set app entrypoint to `web_app.py`.

## Persistence behavior
- Uploaded PDF files are saved under `data/syllabi/` with unique IDs.
- Parsed metadata is stored in `data/syllabi_index.json`.
- Users can select previously uploaded syllabi and delete any saved syllabus from the library.

## Notes
- PDF parsing tries `pypdf` first, then `PyPDF2` fallback.
- PDF export uses fixed sections/table blocks and safe text wrapping/chunking for long lines.
- For Korean text in exported PDFs, the app looks for Nanum/Noto CJK fonts and falls back gracefully.
