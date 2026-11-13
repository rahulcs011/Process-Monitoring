#!/bin/bash
# build_docs.sh - compiles the LaTeX report and the Beamer slides to PDF.
cd "$(dirname "$0")/.."

build() {
    dir=$1; file=$2
    pdf="${file%.tex}.pdf"
    echo "Building $dir/$file ..."
    rm -f "$dir/$pdf"
    if command -v latexmk >/dev/null 2>&1; then
        (cd "$dir" && latexmk -pdf -interaction=nonstopmode -quiet "$file" >/dev/null)
    elif command -v pdflatex >/dev/null 2>&1; then
        # run twice so the table of contents is filled in
        (cd "$dir" && pdflatex -interaction=nonstopmode "$file" >/dev/null; pdflatex -interaction=nonstopmode "$file" >/dev/null)
    elif command -v tectonic >/dev/null 2>&1; then
        (cd "$dir" && tectonic "$file" > build.log 2>&1 || grep -i error build.log)
    else
        echo "No LaTeX compiler found. Install one (brew install tectonic) or upload the .tex to Overleaf."
        return 1
    fi
    if [ ! -f "$dir/$pdf" ]; then
        echo "FAILED: $dir/$file"
        return 1
    fi
}

# fresh charts and the current git history for the report
.venv/bin/python docs/make_figures.py || exit 1
git log --reverse --format='%h  %ad  %s' --date=short > report/gitlog.txt

build report report.tex && build presentation slides.tex || exit 1
ls -l report/report.pdf presentation/slides.pdf
