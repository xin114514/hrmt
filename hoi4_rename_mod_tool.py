from __future__ import annotations

import json
import os
import re
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "钢4改名mod制作工具" 
PROJECT_EXT = ".hoi4rename.json"
PROJECT_VERSION = 1
DEFAULT_IDEOLOGIES = ("fascism", "democratic", "neutrality", "communism")
LANGUAGES = (
    ("simp_chinese", "简体中文"),
    ("english", "English"),
    ("braz_por", "Português"),
    ("french", "Français"),
    ("german", "Deutsch"),
    ("polish", "Polski"),
    ("russian", "Русский"),
    ("spanish", "Español"),
    ("japanese", "日本語"),
)


@dataclass
class RenameRow:
    key: str
    country: str
    ideology: str
    original: str
    new: str = ""


def strip_comments(text: str) -> str:
    """Remove # comments while keeping quoted strings intact."""
    out: list[str] = []
    in_quote = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and in_quote:
            escaped = not escaped
            out.append(ch)
            i += 1
            continue
        if ch == '"' and not escaped:
            in_quote = not in_quote
            out.append(ch)
        elif ch == "#" and not in_quote:
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        else:
            out.append(ch)
        escaped = False
        i += 1
    return "".join(out)


def read_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="ignore")


def find_probable_hoi4_dirs() -> list[Path]:
    candidates: list[Path] = []
    roots = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
    ]
    for root in roots:
        candidates.extend(
            [
                root / "Steam" / "steamapps" / "common" / "Hearts of Iron IV",
                root / "SteamLibrary" / "steamapps" / "common" / "Hearts of Iron IV",
            ]
        )

    for drive in "CDEFGHI":
        candidates.append(Path(f"{drive}:\\SteamLibrary\\steamapps\\common\\Hearts of Iron IV"))

    return [p for p in candidates if is_hoi4_dir(p)]


def is_hoi4_dir(path: Path) -> bool:
    return (
        path.exists()
        and (path / "hoi4.exe").exists()
        and (path / "common").exists()
        and (path / "localisation").exists()
    )


def unquote(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return value.replace('\\"', '"').replace("\\n", "\n")


def is_valid_loc_key(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]+", value))


def parse_localisation(game_dir: Path, language: str) -> tuple[dict[str, str], dict[str, str]]:
    selected: dict[str, str] = {}
    fallback: dict[str, str] = {}
    loc_root = game_dir / "localisation"
    pattern = re.compile(r'^\s*([A-Za-z0-9_.:-]+):\d+\s+"(.*)"\s*$')

    if not loc_root.exists():
        return selected, fallback

    for path in loc_root.rglob("*.yml"):
        text = read_text(path)
        target = selected if f"_l_{language}.yml" in path.name else fallback
        for line in text.splitlines():
            match = pattern.match(line)
            if match:
                target[match.group(1)] = unquote(match.group(2))

    return selected, fallback


def loc_lookup(key: str, selected: dict[str, str], fallback: dict[str, str]) -> str:
    return selected.get(key) or fallback.get(key) or key


def country_display(tag: str, selected: dict[str, str], fallback: dict[str, str], history_name: str = "") -> str:
    name = loc_lookup(tag, selected, fallback)
    if name == tag:
        name = history_name or tag
    return f"{tag} / {name}" if name != tag else tag


def parse_country_tags(game_dir: Path) -> dict[str, str]:
    tags: dict[str, str] = {}
    tag_dir = game_dir / "common" / "country_tags"
    line_re = re.compile(r'^\s*([A-Z0-9]{3})\s*=\s*"([^"]+)"')
    if not tag_dir.exists():
        return tags

    for path in tag_dir.rglob("*.txt"):
        for line in strip_comments(read_text(path)).splitlines():
            match = line_re.match(line)
            if match:
                tags[match.group(1)] = match.group(2)
    return dict(sorted(tags.items()))


def parse_history_country_names(game_dir: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    history_dir = game_dir / "history" / "countries"
    if not history_dir.exists():
        return names
    for path in history_dir.glob("*.txt"):
        match = re.match(r"([A-Z0-9]{3})\s*-\s*(.+)\.txt$", path.name)
        if match:
            names[match.group(1)] = match.group(2)
    return names


def parse_country_rows(
    tags: dict[str, str],
    history_names: dict[str, str],
    selected_loc: dict[str, str],
    fallback_loc: dict[str, str],
) -> list[RenameRow]:
    rows: list[RenameRow] = []
    all_keys = set(selected_loc) | set(fallback_loc)

    for tag in tags:
        country_label = country_display(tag, selected_loc, fallback_loc, history_names.get(tag, ""))

        ideologies = [
            ideology
            for ideology in DEFAULT_IDEOLOGIES
            if f"{tag}_{ideology}" in all_keys or tag in all_keys
        ]

        generic = loc_lookup(tag, selected_loc, fallback_loc)
        if generic != tag:
            rows.append(RenameRow(key=tag, country=country_label, ideology="国家通用名", original=generic))

        for ideology in ideologies:
            loc_key = f"{tag}_{ideology}"
            original = loc_lookup(loc_key, selected_loc, fallback_loc)
            if original == loc_key:
                original = generic if generic != tag else country_label
            rows.append(RenameRow(key=loc_key, country=country_label, ideology=ideology, original=original))

    return rows


def find_matching_brace(text: str, start_brace: int) -> int:
    depth = 0
    in_quote = False
    escaped = False
    for i in range(start_brace, len(text)):
        ch = text[i]
        if ch == "\\" and in_quote:
            escaped = not escaped
            continue
        if ch == '"' and not escaped:
            in_quote = not in_quote
        elif not in_quote:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
        escaped = False
    return -1


def parse_character_blocks(text: str) -> dict[str, str]:
    cleaned = strip_comments(text)
    start_match = re.search(r"\bcharacters\s*=\s*\{", cleaned)
    if not start_match:
        return {}

    start_brace = cleaned.find("{", start_match.start())
    end_brace = find_matching_brace(cleaned, start_brace)
    if end_brace == -1:
        return {}

    body = cleaned[start_brace + 1 : end_brace]
    blocks: dict[str, str] = {}
    i = 0
    while i < len(body):
        match = re.search(r"\b([A-Za-z0-9_.:-]+)\s*=\s*\{", body[i:])
        if not match:
            break
        key = match.group(1)
        brace = i + match.end() - 1
        block_end = find_matching_brace(body, brace)
        if block_end == -1:
            break
        blocks[key] = body[brace + 1 : block_end]
        i = block_end + 1
    return blocks


def parse_character_rows(
    game_dir: Path,
    selected_loc: dict[str, str],
    fallback_loc: dict[str, str],
) -> list[RenameRow]:
    rows: list[RenameRow] = []
    char_dir = game_dir / "common" / "characters"
    if not char_dir.exists():
        return rows

    name_re = re.compile(r'\bname\s*=\s*("[^"]+"|[A-Za-z0-9_.:-]+)')
    ideology_re = re.compile(r"\bideology\s*=\s*([A-Za-z0-9_.:-]+)")

    for path in char_dir.rglob("*.txt"):
        blocks = parse_character_blocks(read_text(path))
        for char_key, block in blocks.items():
            name_match = name_re.search(block)
            if not name_match:
                continue
            raw_name = name_match.group(1)
            if raw_name.startswith('"'):
                name_key = unquote(raw_name)
                if not is_valid_loc_key(name_key):
                    continue
            else:
                name_key = raw_name

            if not name_key:
                continue
            original = loc_lookup(name_key, selected_loc, fallback_loc)

            country_tag = char_key[:3].upper() if re.match(r"^[A-Za-z0-9]{3}[_:.]", char_key) else ""
            country = country_display(country_tag, selected_loc, fallback_loc) if country_tag else ""
            ideologies = sorted(set(ideology_re.findall(block))) or ["人物"]
            rows.append(
                RenameRow(
                    key=name_key,
                    country=country,
                    ideology=", ".join(ideologies),
                    original=original,
                )
            )

    unique: dict[tuple[str, str, str], RenameRow] = {}
    for row in rows:
        unique[(row.key, row.country, row.ideology)] = row
    return sorted(unique.values(), key=lambda r: (r.country, r.key, r.ideology))


def scan_game(game_dir: Path, language: str) -> list[RenameRow]:
    selected_loc, fallback_loc = parse_localisation(game_dir, language)
    tags = parse_country_tags(game_dir)
    history_names = parse_history_country_names(game_dir)
    rows = parse_country_rows(tags, history_names, selected_loc, fallback_loc)
    rows.extend(parse_character_rows(game_dir, selected_loc, fallback_loc))
    return rows


def escape_loc(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def write_utf8_sig(path: Path, lines: list[str]) -> None:
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig", newline="")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def row_from_dict(data: dict[str, str]) -> RenameRow:
    return RenameRow(
        key=str(data.get("key", "")),
        country=str(data.get("country", "")),
        ideology=str(data.get("ideology", "")),
        original=str(data.get("original", "")),
        new=str(data.get("new", "")),
    )


def merge_rows(scanned: list[RenameRow], saved: list[RenameRow]) -> list[RenameRow]:
    saved_new = {row.key: row.new for row in saved if row.new.strip()}
    for row in scanned:
        if row.key in saved_new:
            row.new = saved_new[row.key]

    scanned_keys = {row.key for row in scanned}
    stale_rows = [row for row in saved if row.key not in scanned_keys and row.new.strip()]
    return scanned + stale_rows


def default_mod_dir() -> Path:
    return Path.home() / "Documents" / "Paradox Interactive" / "Hearts of Iron IV" / "mod"


def write_mod(mod_root: Path, mod_name: str, language: str, rows: list[RenameRow]) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_\- ]+", "", mod_name).strip() or "HOI4 Rename Mod"
    folder_name = re.sub(r"\s+", "_", safe_name).lower()
    mod_folder = mod_root / folder_name

    (mod_folder / "localisation" / "replace").mkdir(parents=True, exist_ok=True)

    changed = [row for row in rows if row.new.strip()]
    loc_lines = [f"l_{language}:"]
    for row in sorted(changed, key=lambda r: r.key):
        loc_lines.append(f' {row.key}:0 "{escape_loc(row.new.strip())}"')

    loc_path = mod_folder / "localisation" / "replace" / f"{folder_name}_l_{language}.yml"
    write_utf8_sig(loc_path, loc_lines)

    descriptor_text = (
        'version="1.0"\n'
        'tags={\n'
        '\t"Alternative History"\n'
        '}\n'
        f'name="{safe_name}"\n'
        'supported_version="*"\n'
    )
    (mod_folder / "descriptor.mod").write_text(descriptor_text, encoding="utf-8")

    launcher_descriptor = (
        f'name="{safe_name}"\n'
        f'path="mod/{folder_name}"\n'
        'tags={\n'
        '\t"Alternative History"\n'
        '}\n'
        'supported_version="*"\n'
        'version="1.0"\n'
    )
    mod_root.mkdir(parents=True, exist_ok=True)
    (mod_root / f"{folder_name}.mod").write_text(launcher_descriptor, encoding="utf-8")
    return mod_folder


class RenameModApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x740")
        self.minsize(980, 600)
        self._configure_chinese_fonts()

        self.rows: list[RenameRow] = []
        self.filtered_indices: list[int] = []
        self.editor: tk.Entry | None = None
        self.current_project_path: Path | None = None

        self.project_name_var = tk.StringVar(value="新项目")
        self.game_dir_var = tk.StringVar()
        self.mod_dir_var = tk.StringVar(value=str(default_mod_dir()))
        self.mod_name_var = tk.StringVar(value="HOI4 Rename Mod")
        self.language_var = tk.StringVar(value="simp_chinese")
        self.filter_var = tk.StringVar()
        self.status_var = tk.StringVar(value="在项目面板创建或打开一个项目。")
        self.project_info_var = tk.StringVar(value="尚未打开项目")

        self.project_frame = ttk.Frame(self)
        self.workbench_frame = ttk.Frame(self)

        self._build_project_panel()
        self._build_workbench()
        self._fill_probable_game_dir()
        self.show_project_panel()

    def _configure_chinese_fonts(self) -> None:
        available = set(tkfont.families(self))
        family = next(
            (name for name in ("Microsoft YaHei UI", "Microsoft YaHei", "SimSun", "Noto Sans CJK SC") if name in available),
            "",
        )
        if not family:
            return

        for font_name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkTooltipFont"):
            try:
                font = tkfont.nametofont(font_name)
                font.configure(family=family)
            except tk.TclError:
                continue

    def _build_project_panel(self) -> None:
        self.project_frame.columnconfigure(0, weight=1)
        self.project_frame.rowconfigure(1, weight=1)

        title = ttk.Label(self.project_frame, text="项目面板", font=("Microsoft YaHei UI", 20, "bold"))
        title.grid(row=0, column=0, sticky=tk.W, padx=24, pady=(24, 8))

        body = ttk.Frame(self.project_frame)
        body.grid(row=1, column=0, sticky=tk.NSEW, padx=24, pady=16)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        create_box = ttk.LabelFrame(body, text="创建 MOD 项目")
        create_box.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 12), pady=0)
        create_box.columnconfigure(1, weight=1)

        pad = {"padx": 10, "pady": 7}
        ttk.Label(create_box, text="项目名称").grid(row=0, column=0, sticky=tk.W, **pad)
        ttk.Entry(create_box, textvariable=self.project_name_var).grid(row=0, column=1, sticky=tk.EW, **pad)
        ttk.Label(create_box, text="MOD 名称").grid(row=1, column=0, sticky=tk.W, **pad)
        ttk.Entry(create_box, textvariable=self.mod_name_var).grid(row=1, column=1, sticky=tk.EW, **pad)
        ttk.Label(create_box, text="语言").grid(row=2, column=0, sticky=tk.W, **pad)
        language_box = ttk.Combobox(create_box, textvariable=self.language_var, state="readonly", width=16)
        language_box["values"] = [code for code, _ in LANGUAGES]
        language_box.grid(row=2, column=1, sticky=tk.W, **pad)
        ttk.Label(create_box, text="原版目录").grid(row=3, column=0, sticky=tk.W, **pad)
        ttk.Entry(create_box, textvariable=self.game_dir_var).grid(row=3, column=1, sticky=tk.EW, **pad)
        ttk.Button(create_box, text="浏览原版目录", command=self.choose_game_dir).grid(row=4, column=1, sticky=tk.W, **pad)
        ttk.Label(create_box, text="MOD 输出目录").grid(row=5, column=0, sticky=tk.W, **pad)
        ttk.Entry(create_box, textvariable=self.mod_dir_var).grid(row=5, column=1, sticky=tk.EW, **pad)
        ttk.Button(create_box, text="浏览输出目录", command=self.choose_mod_dir).grid(row=6, column=1, sticky=tk.W, **pad)
        ttk.Button(create_box, text="创建项目并进入工作台", command=self.create_project).grid(row=7, column=1, sticky=tk.E, **pad)

        open_box = ttk.LabelFrame(body, text="打开存档")
        open_box.grid(row=0, column=1, sticky=tk.NSEW, padx=(12, 0), pady=0)
        open_box.columnconfigure(0, weight=1)
        ttk.Label(
            open_box,
            text="项目存档会保存已扫描的 key、已填写的新名称、目录和 MOD 设置。打开后可以继续修改、重新扫描并再次生成 MOD。存档文件的格式应当是xxx.hoi4rename.json。",
            wraplength=430,
        ).grid(row=0, column=0, sticky=tk.W, padx=12, pady=(14, 8))
        ttk.Button(open_box, text="打开项目存档", command=self.open_project_dialog).grid(row=1, column=0, sticky=tk.W, padx=12, pady=8)

        

    def _build_workbench(self) -> None:
        self.workbench_frame.columnconfigure(0, weight=1)
        self.workbench_frame.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(self.workbench_frame)
        toolbar.grid(row=0, column=0, sticky=tk.EW, padx=10, pady=(10, 2))
        toolbar.columnconfigure(4, weight=1)

        ttk.Button(toolbar, text="返回", command=self.show_project_panel).grid(row=0, column=0, padx=5, pady=5)
        ttk.Button(toolbar, text="存档", command=self.save_project).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(toolbar, text="另存为", command=self.save_project_as).grid(row=0, column=2, padx=5, pady=5)
        ttk.Button(toolbar, text="打开存档", command=self.open_project_dialog).grid(row=0, column=3, padx=5, pady=5)
        ttk.Label(toolbar, textvariable=self.project_info_var, anchor=tk.W).grid(row=0, column=4, sticky=tk.EW, padx=8)

        top = ttk.Frame(self.workbench_frame)
        top.grid(row=1, column=0, sticky=tk.EW, padx=10, pady=(2, 2))
        pad = {"padx": 8, "pady": 5}

        ttk.Label(top, text="原版目录").grid(row=0, column=0, sticky=tk.W, **pad)
        ttk.Entry(top, textvariable=self.game_dir_var).grid(row=0, column=1, sticky=tk.EW, **pad)
        ttk.Button(top, text="浏览", command=self.choose_game_dir).grid(row=0, column=2, **pad)
        ttk.Button(top, text="扫描/合并原版", command=self.scan).grid(row=0, column=3, **pad)

        ttk.Label(top, text="语言").grid(row=0, column=4, sticky=tk.E, **pad)
        language_box = ttk.Combobox(top, textvariable=self.language_var, state="readonly", width=14)
        language_box["values"] = [code for code, _ in LANGUAGES]
        language_box.grid(row=0, column=5, sticky=tk.W, **pad)

        ttk.Label(top, text="项目名称").grid(row=1, column=0, sticky=tk.W, **pad)
        ttk.Entry(top, textvariable=self.project_name_var).grid(row=1, column=1, sticky=tk.EW, **pad)
        ttk.Label(top, text="MOD 名称").grid(row=1, column=2, sticky=tk.E, **pad)
        ttk.Entry(top, textvariable=self.mod_name_var).grid(row=1, column=3, sticky=tk.EW, **pad)
        ttk.Label(top, text="输出目录").grid(row=1, column=4, sticky=tk.E, **pad)
        ttk.Entry(top, textvariable=self.mod_dir_var).grid(row=1, column=5, sticky=tk.EW, **pad)
        ttk.Button(top, text="浏览", command=self.choose_mod_dir).grid(row=1, column=6, **pad)
        ttk.Button(top, text="一键生成 MOD", command=self.generate_mod).grid(row=1, column=7, **pad)

        ttk.Label(top, text="过滤").grid(row=2, column=0, sticky=tk.W, **pad)
        filter_entry = ttk.Entry(top, textvariable=self.filter_var)
        filter_entry.grid(row=2, column=1, columnspan=7, sticky=tk.EW, **pad)
        filter_entry.bind("<KeyRelease>", lambda _event: self.refresh_table())

        top.columnconfigure(1, weight=2)
        top.columnconfigure(3, weight=1)
        top.columnconfigure(5, weight=1)

        table_frame = ttk.Frame(self.workbench_frame)
        table_frame.grid(row=2, column=0, sticky=tk.NSEW, padx=10, pady=8)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("key", "country", "ideology", "original", "new")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "key": "key",
            "country": "国家",
            "ideology": "意识形态",
            "original": "原版人物（国家）名",
            "new": "新人物(国家）名",
        }
        widths = {"key": 260, "country": 150, "ideology": 160, "original": 260, "new": 280}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor=tk.W, stretch=True)

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky=tk.NSEW)
        y_scroll.grid(row=0, column=1, sticky=tk.NS)
        x_scroll.grid(row=1, column=0, sticky=tk.EW)

        self.tree.bind("<Double-1>", self.begin_edit)
        self.tree.bind("<Return>", self.begin_edit)
        self.tree.bind("<Button-1>", self.close_editor)

        status = ttk.Label(self.workbench_frame, textvariable=self.status_var, anchor=tk.W)
        status.grid(row=3, column=0, sticky=tk.EW, padx=10, pady=(0, 8))

    def show_project_panel(self) -> None:
        self.close_editor()
        self.workbench_frame.pack_forget()
        self.project_frame.pack(fill=tk.BOTH, expand=True)
        self.title(f"{APP_TITLE} - 项目面板")

    def show_workbench(self) -> None:
        self.project_frame.pack_forget()
        self.workbench_frame.pack(fill=tk.BOTH, expand=True)
        self.update_project_info()
        self.title(f"{APP_TITLE} - 工作台")

    def update_project_info(self) -> None:
        path_text = str(self.current_project_path) if self.current_project_path else "未存档"
        changed = sum(1 for row in self.rows if row.new.strip())
        self.project_info_var.set(f"项目：{self.project_name_var.get()} | 已改名：{changed} | 存档：{path_text}")

    def _fill_probable_game_dir(self) -> None:
        dirs = find_probable_hoi4_dirs()
        if dirs:
            self.game_dir_var.set(str(dirs[0]))
            self.status_var.set(f"已自动找到可能的原版目录：{dirs[0]}")

    def create_project(self) -> None:
        self.current_project_path = None
        self.rows = []
        self.filter_var.set("")
        self.refresh_table()
        self.status_var.set("项目已创建。请在工作台扫描原版目录，填写新名称后存档或生成 MOD。")
        self.show_workbench()

    def choose_game_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 Hearts of Iron IV 原版安装目录")
        if path:
            self.game_dir_var.set(path)

    def choose_mod_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 HOI4 mod 输出目录")
        if path:
            self.mod_dir_var.set(path)

    def project_payload(self) -> dict[str, object]:
        return {
            "project_version": PROJECT_VERSION,
            "project_name": self.project_name_var.get(),
            "mod_name": self.mod_name_var.get(),
            "game_dir": self.game_dir_var.get(),
            "mod_dir": self.mod_dir_var.get(),
            "language": self.language_var.get(),
            "saved_at": now_text(),
            "rows": [asdict(row) for row in self.rows],
        }

    def load_project_payload(self, payload: dict[str, object], path: Path) -> None:
        self.current_project_path = path
        self.project_name_var.set(str(payload.get("project_name", path.stem)))
        self.mod_name_var.set(str(payload.get("mod_name", "HOI4 Rename Mod")))
        self.game_dir_var.set(str(payload.get("game_dir", "")))
        self.mod_dir_var.set(str(payload.get("mod_dir", default_mod_dir())))
        self.language_var.set(str(payload.get("language", "simp_chinese")))
        raw_rows = payload.get("rows", [])
        self.rows = [row_from_dict(row) for row in raw_rows if isinstance(row, dict)]
        self.filter_var.set("")
        self.refresh_table()
        self.status_var.set(f"已打开存档：{path}")
        self.show_workbench()

    def save_project(self) -> bool:
        self.close_editor()
        if not self.current_project_path:
            return self.save_project_as()
        try:
            self.current_project_path.write_text(
                json.dumps(self.project_payload(), ensure_ascii=False, indent=2),
                encoding="utf-8-sig",
            )
        except Exception as exc:
            messagebox.showerror("存档失败", str(exc))
            return False
        self.status_var.set(f"已存档：{self.current_project_path}")
        self.update_project_info()
        return True

    def save_project_as(self) -> bool:
        self.close_editor()
        default_name = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff ]+", "", self.project_name_var.get()).strip()
        if not default_name:
            default_name = "HOI4 改名项目"
        path = filedialog.asksaveasfilename(
            title="保存项目存档",
            defaultextension=PROJECT_EXT,
            initialfile=f"{default_name}{PROJECT_EXT}",
            filetypes=(("HOI4 改名项目", f"*{PROJECT_EXT}"), ("JSON 文件", "*.json"), ("所有文件", "*.*")),
        )
        if not path:
            return False
        self.current_project_path = Path(path)
        return self.save_project()

    def open_project_dialog(self) -> None:
        path = filedialog.askopenfilename(
            title="打开项目存档",
            filetypes=(("HOI4 改名项目", f"*{PROJECT_EXT}"), ("JSON 文件", "*.json"), ("所有文件", "*.*")),
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))
            return
        if not isinstance(payload, dict):
            messagebox.showerror("打开失败", "项目存档格式不正确。")
            return
        self.load_project_payload(payload, Path(path))

    def scan(self) -> None:
        game_dir = Path(self.game_dir_var.get()).expanduser()
        if not is_hoi4_dir(game_dir):
            messagebox.showerror("目录不正确", "请选择 Hearts of Iron IV 原版安装目录，目录下应包含 hoi4.exe、common、localisation。")
            return

        try:
            self.status_var.set("正在扫描原版文件，请稍候...")
            self.update_idletasks()
            scanned = scan_game(game_dir, self.language_var.get())
            self.rows = merge_rows(scanned, self.rows)
            self.refresh_table()
            self.status_var.set(f"扫描完成：共整理 {len(self.rows)} 个国家/人物本地化 key，已保留已有改名。")
            self.update_project_info()
        except Exception as exc:
            messagebox.showerror("扫描失败", str(exc))
            self.status_var.set("扫描失败。")

    def refresh_table(self) -> None:
        self.close_editor()
        query = self.filter_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        self.filtered_indices = []
        for index, row in enumerate(self.rows):
            haystack = f"{row.key} {row.country} {row.ideology} {row.original} {row.new}".lower()
            if query and query not in haystack:
                continue
            iid = str(index)
            self.filtered_indices.append(index)
            self.tree.insert("", tk.END, iid=iid, values=(row.key, row.country, row.ideology, row.original, row.new))
        self.update_project_info()

    def begin_edit(self, event: tk.Event | None = None) -> None:
        self.close_editor()
        if event is not None:
            region = self.tree.identify("region", event.x, event.y)
            if region != "cell":
                return
            column = self.tree.identify_column(event.x)
            item = self.tree.identify_row(event.y)
        else:
            item = self.tree.focus()
            column = "#5"

        if not item or column != "#5":
            return

        bbox = self.tree.bbox(item, column)
        if not bbox:
            return
        x, y, width, height = bbox
        row = self.rows[int(item)]

        self.editor = tk.Entry(self.tree)
        self.editor.insert(0, row.new)
        self.editor.select_range(0, tk.END)
        self.editor.focus_set()
        self.editor.place(x=x, y=y, width=width, height=height)
        self.editor.bind("<Return>", lambda _event: self.save_editor(item))
        self.editor.bind("<Escape>", lambda _event: self.close_editor())
        self.editor.bind("<FocusOut>", lambda _event: self.save_editor(item))

    def save_editor(self, item: str) -> None:
        if not self.editor:
            return
        self.rows[int(item)].new = self.editor.get()
        values = list(self.tree.item(item, "values"))
        values[4] = self.rows[int(item)].new
        self.tree.item(item, values=values)
        self.close_editor()
        self.update_project_info()

    def close_editor(self, _event: tk.Event | None = None) -> None:
        if self.editor:
            self.editor.destroy()
            self.editor = None

    def generate_mod(self) -> None:
        self.close_editor()
        if not self.rows:
            messagebox.showwarning("没有数据", "请先扫描原版目录。")
            return
        changed = sum(1 for row in self.rows if row.new.strip())
        if changed == 0:
            messagebox.showwarning("没有新名称", "请至少在最后一列填写一个新名称。")
            return

        mod_root = Path(self.mod_dir_var.get()).expanduser()
        try:
            mod_folder = write_mod(mod_root, self.mod_name_var.get(), self.language_var.get(), self.rows)
        except Exception as exc:
            messagebox.showerror("生成失败", str(exc))
            return

        self.save_project()
        self.status_var.set(f"已生成 MOD：{mod_folder}，包含 {changed} 个改名 key。")
        messagebox.showinfo("生成完成", f"MOD 已生成：\n{mod_folder}\n\n在 HOI4 启动器中启用即可。")


def main() -> int:
    app = RenameModApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
