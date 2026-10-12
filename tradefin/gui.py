"""Desktop interface for running the Tradefin document pipeline."""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from dotenv import load_dotenv
from openai import OpenAI

from .errors import TradefinError
from .model_catalog import DEFAULT_MODEL, MODEL_ID_BY_LABEL, MODEL_LABEL_BY_ID
from .pipeline import run_pipeline

FILE_TYPES = [
    ("PDF and image files", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
    ("PDF files", "*.pdf"),
    ("Image files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
    ("All files", "*.*"),
]


class TradefinApp:
    """Tkinter front end that keeps long OCR/API work off the UI thread."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Tradefin · Commercial Invoice Builder")
        self.root.geometry("960x760")
        self.root.minsize(760, 620)
        self._results: queue.Queue[tuple[str, object]] = queue.Queue()
        self._bl_paths: list[Path] = []
        self._coa_paths: list[Path] = []

        self.lc_var = tk.StringVar()
        self.bl_var = tk.StringVar(value="No files selected")
        self.coa_var = tk.StringVar(value="No files selected")
        self.template_var = tk.StringVar(value="inputs/template.docx.docx")
        self.output_var = tk.StringVar(value="outputs")
        self.backend_var = tk.StringVar(value="Vision (page images)")
        self.model_var = tk.StringVar(value=MODEL_LABEL_BY_ID[DEFAULT_MODEL])
        self.status_var = tk.StringVar(value="Choose a Letter of Credit to begin.")

        self._build()

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        body = ttk.Frame(self.root, padding=16)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="Create a Commercial Invoice", font=("Segoe UI", 18, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        ttk.Label(
            body,
            text="Select the source documents. Tradefin will extract their fields and fill the invoice template.",
            wraplength=850,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 14))

        self._file_row(body, 2, "Letter of Credit *", self.lc_var, self._choose_lc)
        self._file_row(body, 3, "Bills of Lading", self.bl_var, self._choose_bl)
        self._file_row(body, 4, "Certificates of Analysis", self.coa_var, self._choose_coa)
        self._file_row(body, 5, "Word template", self.template_var, self._choose_template)
        self._file_row(body, 6, "Output folder", self.output_var, self._choose_output)

        ttk.Label(body, text="OpenAI model").grid(row=7, column=0, sticky="nw", padx=(0, 12), pady=8)
        model_picker = ttk.Combobox(
            body,
            textvariable=self.model_var,
            values=tuple(MODEL_ID_BY_LABEL),
            state="readonly",
            width=30,
        )
        model_picker.grid(row=7, column=1, sticky="nw", pady=8)

        ttk.Label(body, text="OCR backend").grid(row=8, column=0, sticky="nw", padx=(0, 12), pady=8)
        backend = ttk.Combobox(
            body,
            textvariable=self.backend_var,
            values=("Vision (page images)", "PaddleOCR (local)"),
            state="readonly",
            width=24,
        )
        backend.grid(row=8, column=1, sticky="nw", pady=8)
        ttk.Label(
            body,
            text="PaddleOCR runs locally before field extraction and may download OCR models the first time.",
            wraplength=700,
        ).grid(row=9, column=1, columnspan=2, sticky="w", pady=(0, 6))

        actions = ttk.Frame(body)
        actions.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(8, 10))
        actions.columnconfigure(1, weight=1)
        self.run_button = ttk.Button(actions, text="Create invoice", command=self._start)
        self.run_button.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(actions, mode="indeterminate")
        self.progress.grid(row=0, column=1, sticky="ew", padx=12)
        ttk.Label(actions, textvariable=self.status_var).grid(row=0, column=2, sticky="e")

        ttk.Label(body, text="Extracted fields").grid(
            row=11, column=0, columnspan=3, sticky="w", pady=(6, 4)
        )
        self.fields_text = tk.Text(body, height=18, wrap="word", state="disabled", undo=False)
        self.fields_text.grid(row=12, column=0, columnspan=3, sticky="nsew")
        body.rowconfigure(12, weight=1)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.fields_text.yview)
        scrollbar.grid(row=12, column=3, sticky="ns")
        self.fields_text.configure(yscrollcommand=scrollbar.set)

    @staticmethod
    def _file_row(
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command: Callable[[], None],
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Button(parent, text="Browse…", command=command).grid(
            row=row, column=2, sticky="e", padx=(8, 0), pady=5
        )

    def _choose_lc(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="Choose a Letter of Credit", filetypes=FILE_TYPES)
        if path:
            self.lc_var.set(path)

    def _choose_bl(self) -> None:
        self._bl_paths = self._choose_many("Choose Bill of Lading files")
        self.bl_var.set(self._selection_label(self._bl_paths))

    def _choose_coa(self) -> None:
        self._coa_paths = self._choose_many("Choose Certificate of Analysis files")
        self.coa_var.set(self._selection_label(self._coa_paths))

    def _choose_many(self, title: str) -> list[Path]:
        names = filedialog.askopenfilenames(parent=self.root, title=title, filetypes=FILE_TYPES)
        return [Path(name) for name in names]

    @staticmethod
    def _selection_label(paths: list[Path]) -> str:
        if not paths:
            return "No files selected"
        names = ", ".join(path.name for path in paths[:3])
        remainder = len(paths) - 3
        if remainder > 0:
            names += f", and {remainder} more"
        return f"{len(paths)} file(s): {names}"

    def _choose_template(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Choose a Word invoice template",
            filetypes=[("Word documents", "*.docx"), ("All files", "*.*")],
        )
        if path:
            self.template_var.set(path)

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(parent=self.root, title="Choose output folder")
        if path:
            self.output_var.set(path)

    def _start(self) -> None:
        lc = Path(self.lc_var.get().strip())
        if not lc.is_file():
            messagebox.showerror("Letter of Credit required", "Choose an existing LC PDF or image.", parent=self.root)
            return
        template = Path(self.template_var.get().strip())
        if not template.is_file():
            messagebox.showerror("Template not found", f"Choose an existing Word template.\n\n{template}", parent=self.root)
            return
        load_dotenv()
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            messagebox.showerror(
                "API key missing",
                "Set OPENAI_API_KEY in the project .env file or environment, then reopen this app.",
                parent=self.root,
            )
            return

        backend = "paddle" if self.backend_var.get().startswith("PaddleOCR") else "vision"
        model = MODEL_ID_BY_LABEL[self.model_var.get()]
        bl_paths = list(self._bl_paths)
        coa_paths = list(self._coa_paths)
        self.run_button.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Reading documents and extracting fields…")
        self.fields_text.configure(state="normal")
        self.fields_text.delete("1.0", "end")
        self.fields_text.configure(state="disabled")

        worker = threading.Thread(
            target=self._run_worker,
            args=(lc, bl_paths, coa_paths, template, Path(self.output_var.get().strip() or "outputs"), backend, model, api_key),
            daemon=True,
        )
        worker.start()
        self.root.after(150, self._poll_result)

    def _run_worker(
        self,
        lc: Path,
        bl_paths: list[Path],
        coa_paths: list[Path],
        template: Path,
        output_dir: Path,
        backend: str,
        model: str,
        api_key: str,
    ) -> None:
        try:
            fields, output_path = run_pipeline(
                lc=lc,
                bills_of_lading=bl_paths,
                certificates=coa_paths,
                output_dir=output_dir,
                template=template,
                ocr_backend=backend,
                model=model,
                client=OpenAI(api_key=api_key),
            )
            self._results.put(("success", (fields, output_path)))
        except (TradefinError, OSError) as exc:
            self._results.put(("error", str(exc)))
        except Exception as exc:
            self._results.put(("error", f"Unexpected error: {exc}"))

    def _poll_result(self) -> None:
        try:
            status, payload = self._results.get_nowait()
        except queue.Empty:
            self.root.after(150, self._poll_result)
            return

        self.progress.stop()
        self.run_button.configure(state="normal")
        if status == "error":
            self.status_var.set("Invoice creation failed.")
            messagebox.showerror("Could not create invoice", str(payload), parent=self.root)
            return

        fields, output_path = payload
        self.fields_text.configure(state="normal")
        for name, value in fields.model_dump().items():
            self.fields_text.insert("end", f"{name}\n{value or '—'}\n\n")
        self.fields_text.configure(state="disabled")
        self.status_var.set(f"Saved: {output_path}")
        messagebox.showinfo("Invoice created", f"Commercial Invoice saved to:\n{output_path}", parent=self.root)


def main() -> None:
    root = tk.Tk()
    TradefinApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
