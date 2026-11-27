-- Display equations from PDFs are kept as pictures cropped from the page.
-- `asset` is the file name in library/assets/<document id>/ ('' when the paragraph has none).
ALTER TABLE paragraphs ADD COLUMN asset TEXT NOT NULL DEFAULT '';
