"""Windows interface for the offline role builder."""

import json
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from role_builder import build, verify
from viewer_formats import convert_package, inspect_source


FORMATS = (("ZIP 角色包", "*.zip"), ("LPK 角色包", "*.lpk"), ("WPK 角色包", "*.wpk"))


def launch():
    root = tk.Tk()
    root.title("LovePetTool")
    root.minsize(580, 350)
    root.resizable(True, True)
    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    frame.rowconfigure(5, weight=1)
    source = tk.StringVar()
    output = tk.StringVar()
    runtime = tk.StringVar()
    package_format = tk.StringVar(value="ZIP")
    status = tk.StringVar(value="等待选择素材文件夹或角色包")
    results = SimpleQueue()
    actions = []

    def choose_folder():
        directory = filedialog.askdirectory(parent=root, title="选择整理好的角色素材文件夹")
        if directory:
            source.set(directory)
            suggest(Path(directory).name, Path(directory).parent)

    def choose_package():
        file = filedialog.askopenfilename(parent=root, title="选择角色包", filetypes=(("角色包", "*.zip *.lpk *.wpk"), *FORMATS))
        if file:
            source.set(file)
            suggest(Path(file).stem + "-mobile", Path(file).parent)

    def suggest(name, directory):
        output.set(str(directory / (name + "." + package_format.get().lower())))

    def update_format(_event):
        if output.get():
            output.set(str(Path(output.get()).with_suffix("." + package_format.get().lower())))

    def choose_output():
        suffix = "." + package_format.get().lower()
        current = (Path(output.get()) if output.get() else Path("role")).with_suffix(suffix)
        selected_format = tuple(item for item in FORMATS if item[1] == "*" + suffix)
        file = filedialog.asksaveasfilename(parent=root, title="选择角色包保存位置", filetypes=selected_format,
                                            initialdir=current.parent, initialfile=current.name, defaultextension=suffix)
        if file:
            output.set(file)
            if Path(file).suffix.lower() in {".zip", ".lpk", ".wpk"}:
                package_format.set(Path(file).suffix[1:].upper())

    def choose_runtime():
        path = filedialog.askdirectory(parent=root, title="选择运行库文件所在目录")
        if path:
            runtime.set(path)

    ttk.Label(frame, text="来源").grid(row=0, column=0, sticky="w", pady=4)
    ttk.Entry(frame, textvariable=source).grid(row=0, column=1, sticky="ew", padx=8)
    buttons = ttk.Frame(frame)
    buttons.grid(row=0, column=2, sticky="e")
    ttk.Button(buttons, text="素材文件夹", command=choose_folder).pack(side="left", padx=(0, 4))
    ttk.Button(buttons, text="角色包", command=choose_package).pack(side="left")
    ttk.Label(frame, text="输出文件").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Entry(frame, textvariable=output).grid(row=1, column=1, sticky="ew", padx=8)
    output_picker = ttk.Frame(frame)
    output_picker.grid(row=1, column=2, sticky="e")
    formats = ttk.Combobox(output_picker, textvariable=package_format, values=("ZIP", "LPK", "WPK"), state="readonly", width=5)
    formats.bind("<<ComboboxSelected>>", update_format)
    formats.pack(side="left", padx=(0, 4))
    ttk.Button(output_picker, text="浏览", command=choose_output).pack(side="left")
    ttk.Label(frame, text="运行库目录").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Entry(frame, textvariable=runtime).grid(row=2, column=1, sticky="ew", padx=8)
    ttk.Button(frame, text="浏览", command=choose_runtime).grid(row=2, column=2, sticky="e")
    ttk.Label(frame, text="素材目录内已有 runtime 时可留空。", foreground="#555555").grid(row=3, column=1, sticky="w", padx=8)

    row = ttk.Frame(frame)
    row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(12, 8))
    log = tk.Text(frame, height=9, wrap="word", state="disabled")
    log.grid(row=5, column=0, columnspan=3, sticky="nsew")
    ttk.Label(frame, textvariable=status).grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def process(operation):
        if not source.get().strip() or operation == "create" and not output.get().strip():
            messagebox.showinfo("角色包制作", "请选择来源和所需的输出位置。", parent=root)
            return
        original = Path(source.get().strip())
        target = Path(output.get().strip())
        runtimes = Path(runtime.get().strip()) if runtime.get().strip() else None
        if operation == "create" and target.exists() and not messagebox.askyesno("替换文件", "输出文件已存在，是否替换？", parent=root):
            return
        for button in actions:
            button.configure(state="disabled")
        status.set("处理中…")

        def work():
            try:
                if operation == "inspect":
                    detail = inspect_source(original)
                    results.put((True, json.dumps(detail, ensure_ascii=False, indent=2)))
                else:
                    if original.is_dir():
                        built, _ = build(original, target, runtimes)
                    else:
                        convert_package(original, target, runtimes)
                        built = target.resolve()
                    catalog = verify(built)
                    results.put((True, f"{catalog['name']}\n{built}\n{len(catalog['costumes'])} 件衣装 · {len(catalog['voices'])} 条语音"))
            except Exception as error:
                results.put((False, str(error)))

        def receive():
            try:
                success, detail = results.get_nowait()
            except Empty:
                root.after(100, receive)
                return
            log.configure(state="normal")
            log.delete("1.0", "end")
            log.insert("1.0", detail)
            log.configure(state="disabled")
            status.set("已完成" if success else "请检查素材和配置")
            for button in actions:
                button.configure(state="normal")

        Thread(target=work, daemon=True).start()
        root.after(100, receive)

    for label, operation in (("读取角色包", "inspect"), ("制作或转换", "create")):
        button = ttk.Button(row, text=label, command=lambda current=operation: process(current))
        button.pack(side="left", padx=(0, 8))
        actions.append(button)
    root.mainloop()
