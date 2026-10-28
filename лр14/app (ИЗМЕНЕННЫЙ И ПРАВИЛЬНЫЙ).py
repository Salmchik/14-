
import json
import os
import sqlite3
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog


# BACKEND

FIELDS = {
    "name":    ("Название завода",      str),
    "product": ("Название продукции",   str),
    "output":  ("Годовой выпуск, шт.",  float),
    "cost":    ("Себестоимость, руб.",  float),
    "price":   ("Отпускная цена, руб.", float),
}
TEXT_FIELDS = [k for k, (_, t) in FIELDS.items() if t is str]
NUM_FIELDS = [k for k, (_, t) in FIELDS.items() if t is float]

# Границы интервалов рентабельности (в процентах) для распределения
PROFIT_BINS = [
    (float("-inf"), 0, "убыточные (< 0 %)"),
    (0, 10, "0 – 10 %"),
    (10, 25, "10 – 25 %"),
    (25, 50, "25 – 50 %"),
    (50, float("inf"), "высокая (≥ 50 %)"),
]


class ValidationError(Exception):
    """Ошибка проверки введённых пользователем данных."""


#проверка
def parse_number(text, field_title):
    """Преобразует строку в число (допускает запятую как разделитель)."""
    try:
        return float(str(text).strip().replace(",", ".").replace(" ", ""))
    except ValueError:
        raise ValidationError(f"Поле «{field_title}» должно быть числом.")


def validate_record(raw):
    """Принимает словарь со строковыми значениями, возвращает очищенную запись
    с правильными типами. При ошибке бросает ValidationError."""
    rec = {}
    for key, (title, typ) in FIELDS.items():
        value = raw.get(key, "")
        if typ is str:
            value = str(value).strip()
            if not value:
                raise ValidationError(f"Поле «{title}» не должно быть пустым.")
            rec[key] = value
        else:
            num = parse_number(value, title)
            if num < 0:
                raise ValidationError(f"Поле «{title}» не может быть отрицательным.")
            rec[key] = num
    if rec["cost"] == 0:
        raise ValidationError("Себестоимость должна быть больше 0 "
                              "(иначе нельзя посчитать рентабельность).")
    return rec


#БД
# Файл базы данных лежит рядом с app.py и хранится на диске
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plants.db")


class Database:
    """Хранилище записей на диске (SQLite, модуль sqlite3 из стандартной
    библиотеки) + импорт/экспорт JSON.

    Каждое изменение сразу фиксируется (commit) в файле .db, поэтому данные
    сохраняются между запусками программы. Снаружи записи нумеруются
    позициями 0..n-1 (в порядке добавления), как и раньше."""

    def __init__(self, path=DB_FILE):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS plants (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    name    TEXT NOT NULL,
                    product TEXT NOT NULL,
                    output  REAL NOT NULL CHECK (output >= 0),
                    cost    REAL NOT NULL CHECK (cost > 0),
                    price   REAL NOT NULL CHECK (price >= 0)
                )""")

    def close(self):
        self.conn.close()

    def __len__(self):
        return self.conn.execute("SELECT COUNT(*) FROM plants").fetchone()[0]

    # чтение
    _COLS = ", ".join(FIELDS)

    @staticmethod
    def _to_dict(row):
        return {k: row[k] for k in FIELDS}

    def get_all(self):
        """Все записи списком словарей (в порядке добавления)."""
        rows = self.conn.execute(
            f"SELECT {self._COLS} FROM plants ORDER BY id").fetchall()
        return [self._to_dict(r) for r in rows]

    @property
    def records(self):
        return self.get_all()

    def get(self, index):
        row = self.conn.execute(
            f"SELECT {self._COLS} FROM plants ORDER BY id LIMIT 1 OFFSET ?",
            (index,)).fetchone()
        if row is None:
            raise IndexError(index)
        return self._to_dict(row)

    def _id_at(self, index):
        """Первичный ключ записи, стоящей в позиции index."""
        row = self.conn.execute(
            "SELECT id FROM plants ORDER BY id LIMIT 1 OFFSET ?",
            (index,)).fetchone()
        if row is None:
            raise IndexError(index)
        return row[0]

    def _insert_many(self, recs):
        self.conn.executemany(
            f"INSERT INTO plants ({self._COLS}) VALUES (?, ?, ?, ?, ?)",
            [tuple(r[k] for k in FIELDS) for r in recs])

    #JSON
    def load_json(self, path, append=False):
        """Читает JSON-файл (список записей), проверяет каждую запись и
        записывает их в БД на диске. append=False - заменить содержимое БД,
        True - добавить к существующему. Вся операция - одна транзакция:
        при ошибке БД остаётся без изменений."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValidationError("Корневым элементом JSON должен быть список записей.")
        loaded = []
        for i, item in enumerate(data, 1):
            if not isinstance(item, dict):
                raise ValidationError(f"Запись №{i}: ожидается объект JSON.")
            try:
                loaded.append(validate_record(item))
            except ValidationError as e:
                raise ValidationError(f"Запись №{i}: {e}")
        with self.conn:                      # commit / rollback
            if not append:
                self.conn.execute("DELETE FROM plants")
            self._insert_many(loaded)
        return len(loaded)

    def save_json(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.get_all(), f, ensure_ascii=False, indent=4)

    #CRUD
    def add(self, raw):
        rec = validate_record(raw)
        with self.conn:
            self._insert_many([rec])

    def update(self, index, raw):
        rec = validate_record(raw)
        rid = self._id_at(index)
        with self.conn:
            self.conn.execute(
                "UPDATE plants SET name=?, product=?, output=?, cost=?, price=? "
                "WHERE id=?", tuple(rec[k] for k in FIELDS) + (rid,))

    def delete(self, index):
        rid = self._id_at(index)
        with self.conn:
            self.conn.execute("DELETE FROM plants WHERE id=?", (rid,))

    def clear(self):
        with self.conn:
            self.conn.execute("DELETE FROM plants")

    # поиск
    def search(self, criteria, lenient=False):
        """criteria: {поле: строка}. Возвращает список индексов записей,
        подходящих под ВСЕ непустые критерии.
        Текст - вхождение подстроки без учёта регистра.
        Число - точное значение ("100") или диапазон ("100-500").
        lenient=True (поиск при вводе): недописанное число, например "100-",
        не считается ошибкой, а просто временно не учитывается."""
        result = []
        for i, rec in enumerate(self.get_all()):
            if all(self._match(rec[k], q, k, lenient)
                   for k, q in criteria.items() if q.strip()):
                result.append(i)
        return result

    @staticmethod
    def _match(value, query, key, lenient=False):
        query = query.strip()
        if FIELDS[key][1] is str:
            return query.lower() in value.lower()
        q = query.replace(",", ".")
        # диапазон a-b
        if "-" in q[1:]:
            pos = q.index("-", 1)
            try:
                lo, hi = float(q[:pos]), float(q[pos + 1:])
            except ValueError:
                return lenient
            return lo <= value <= hi
        try:
            return abs(value - float(q)) < 1e-9
        except ValueError:
            return lenient


#расчёты
def natural_volume(rec):
    """Годовой выпуск в натуральном исчислении (штуки)."""
    return rec["output"]


def cost_volume(rec):
    """Годовой выпуск в стоимостном исчислении = выпуск * отпускная цена."""
    return rec["output"] * rec["price"]


def profitability(cost_sum, revenue_sum):
    """Рентабельность, % = (выручка - затраты) / затраты * 100."""
    return (revenue_sum - cost_sum) / cost_sum * 100 if cost_sum else 0.0


def aggregate_by_plant(records):
    """Объединяет записи одного завода (у завода может быть несколько видов
    продукции). Возвращает словарь завод -> агрегированные показатели."""
    plants = {}
    for r in records:
        p = plants.setdefault(r["name"], {"natural": 0.0, "value": 0.0,
                                          "total_cost": 0.0})
        p["natural"] += r["output"]
        p["value"] += r["output"] * r["price"]
        p["total_cost"] += r["output"] * r["cost"]
    for p in plants.values():
        p["profitability"] = profitability(p["total_cost"], p["value"])
    return plants


def min_max(plants, key):
    """Заводы с минимальным и максимальным значением показателя key.
    Возвращает ((имя_min, знач), (имя_max, знач))."""
    lo = min(plants.items(), key=lambda kv: kv[1][key])
    hi = max(plants.items(), key=lambda kv: kv[1][key])
    return (lo[0], lo[1][key]), (hi[0], hi[1][key])


def profitability_distribution(plants):
    """Раскладывает заводы по интервалам рентабельности.
    Возвращает список (название интервала, [(завод, рентабельность), ...])."""
    result = []
    for lo, hi, label in PROFIT_BINS:
        members = [(n, p["profitability"]) for n, p in plants.items()
                   if lo <= p["profitability"] < hi]
        members.sort(key=lambda x: x[1])
        result.append((label, members))
    return result


def compute_all(records):
    """Полная обработка набора данных. Возвращает словарь результатов
    (или None, если БД пуста)."""
    if not records:
        return None
    plants = aggregate_by_plant(records)
    nat_min, nat_max = min_max(plants, "natural")
    val_min, val_max = min_max(plants, "value")
    return {
        "plants": plants,
        "natural_min": nat_min, "natural_max": nat_max,
        "value_min": val_min, "value_max": val_max,
        "distribution": profitability_distribution(plants),
    }



#FRONTEND при помощи ткинтера

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Лабораторная работа 12. Заводы отрасли (вариант 7)")
        self.geometry("1250x720")
        self.minsize(1000, 600)

        self.db = Database()     # БД хранится на диске (plants.db)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.shown = []
        self.entries = {}

        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self.refresh_table()

    # построение 
    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=4)
        bar.pack(fill="x")
        buttons = [
            ("Импорт JSON в БД", self.import_json),
            ("Сохранить в JSON", self.export_json),
            ("Просмотр БД", self.show_all),
            ("Вычислить значения", self.calculate),
            ("Очистить БД", self.clear_db),
        ]
        for text, cmd in buttons:
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=2)

    def _build_body(self):
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=4, pady=4)

        #окно БД и окно результатов
        left = ttk.PanedWindow(paned, orient="vertical")
        paned.add(left, weight=3)

        db_frame = ttk.LabelFrame(left, text="База данных")
        left.add(db_frame, weight=3)
        cols = ("№",) + tuple(FIELDS)
        self.tree = ttk.Treeview(db_frame, columns=cols, show="headings",
                                 selectmode="browse")
        self.tree.heading("№", text="№")
        self.tree.column("№", width=40, anchor="center")
        for key, (title, typ) in FIELDS.items():
            self.tree.heading(key, text=title)
            self.tree.column(key, width=150,
                             anchor="w" if typ is str else "e")
        sb = ttk.Scrollbar(db_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        res_frame = ttk.LabelFrame(left, text="Вычисленные характеристики")
        left.add(res_frame, weight=2)
        self.result_text = tk.Text(res_frame, height=12, wrap="word",
                                   state="disabled", font=("Consolas", 10))
        rsb = ttk.Scrollbar(res_frame, orient="vertical",
                            command=self.result_text.yview)
        self.result_text.configure(yscrollcommand=rsb.set)
        self.result_text.pack(side="left", fill="both", expand=True)
        rsb.pack(side="right", fill="y")

        #поля поиска и редактирования и график
        right = ttk.Frame(paned)
        paned.add(right, weight=1)

        form = ttk.LabelFrame(right, text="Поля поиска и редактирования")
        form.pack(fill="x", padx=2, pady=2)
        for row, (key, (title, _)) in enumerate(FIELDS.items()):
            ttk.Label(form, text=title).grid(row=row, column=0, sticky="w",
                                             padx=4, pady=3)
            e = ttk.Entry(form, width=24)
            e.grid(row=row, column=1, padx=4, pady=3)
            e.bind("<KeyRelease>", self.live_search)   # поиск при каждом вводе
            self.entries[key] = e
        ttk.Label(form, foreground="gray", wraplength=300, justify="left",
                  text="Поиск идёт сразу при вводе букв. Для числа можно указать "
                       "диапазон: 100-500. Чтобы искать заново после выбора строки, "
                       "нажмите «Очистить поля»."
                  ).grid(row=len(FIELDS), column=0, columnspan=2,
                         sticky="w", padx=4)

        btns = ttk.Frame(form)
        btns.grid(row=len(FIELDS) + 1, column=0, columnspan=2, pady=6)
        actions = [
            ("Ввести запись", self.add_record),
            ("Перейти к записи", self.goto_record),
            ("Редактировать запись", self.edit_record),
            ("Удалить запись", self.delete_record),
            ("Поиск по полям", self.search),
            ("Очистить поля", self.reset_search),
        ]
        for i, (text, cmd) in enumerate(actions):
            ttk.Button(btns, text=text, command=cmd, width=20).grid(
                row=i // 2, column=i % 2, padx=2, pady=2)

        chart_frame = ttk.LabelFrame(right, text="Распределение заводов по рентабельности")
        chart_frame.pack(fill="both", expand=True, padx=2, pady=2)
        self.canvas = tk.Canvas(chart_frame, bg="white", height=260)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw_chart())
        self.chart_data = None

    def _build_statusbar(self):
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, relief="sunken",
                  anchor="w").pack(fill="x", side="bottom")

    #таблица
    def refresh_table(self, indices=None):
        """Перерисовывает таблицу. indices=None - показать все записи,
        иначе только записи с указанными индексами (результат поиска)."""
        self.tree.delete(*self.tree.get_children())
        records = self.db.get_all()          # один запрос к диску на всю таблицу
        self.shown = list(range(len(records))) if indices is None else list(indices)
        for i in self.shown:
            rec = records[i]
            values = [i + 1] + [self.fmt(rec[k]) for k in FIELDS]
            self.tree.insert("", "end", iid=str(i), values=values)
        total = len(self.db)
        self.status.set(f"Файл БД: {self.db.path}   |   Записей в БД: {total}. "
                        f"Показано: {len(self.shown)}")

    @staticmethod
    def fmt(value):
        if isinstance(value, float):
            return f"{value:,.2f}".replace(",", " ")
        return value

    def on_select(self, _event=None):
        """При выборе строки таблицы копирует её значения в поля редактирования."""
        sel = self.tree.selection()
        if sel:
            self.fill_fields(self.db.get(int(sel[0])))

    def on_close(self):
        self.db.close()
        self.destroy()

    def selected_index(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Нет выбора", "Выберите запись в таблице.")
            return None
        return int(sel[0])

    #поля ввода
    def fill_fields(self, rec):
        for key, e in self.entries.items():
            e.delete(0, "end")
            v = rec[key]
            e.insert(0, f"{v:g}" if isinstance(v, float) else v)

    def read_fields(self):
        return {k: e.get() for k, e in self.entries.items()}

    def clear_fields(self):
        for e in self.entries.values():
            e.delete(0, "end")

    def reset_search(self):
        """Кнопка «Очистить поля»: очищает поля, снимает выбор, показывает все записи."""
        self.clear_fields()
        self.refresh_table()

    # кнопки
    def import_json(self):
        path = filedialog.askopenfilename(
            title="Выберите JSON-файл",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
        if not path:
            return
        append = False
        if len(self.db):
            ans = messagebox.askyesnocancel(
                "Импорт", "В БД уже есть записи.\n\nДа - добавить к существующим\n"
                          "Нет - заменить БД (старые записи будут удалены с диска)\n"
                          "Отмена - не импортировать")
            if ans is None:
                return
            append = ans
        try:
            n = self.db.load_json(path, append)
        except (OSError, ValueError, sqlite3.Error, ValidationError) as e:
            messagebox.showerror("Ошибка импорта", str(e))
            return
        self.refresh_table()
        messagebox.showinfo("Импорт", f"Импортировано записей: {n}")

    def export_json(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            self.db.save_json(path)
        except (OSError, sqlite3.Error) as e:
            messagebox.showerror("Ошибка сохранения", str(e))
            return
        messagebox.showinfo("Сохранение", "Данные сохранены в JSON.")

    def show_all(self):
        self.refresh_table()

    def add_record(self):
        try:
            self.db.add(self.read_fields())
        except ValidationError as e:
            messagebox.showerror("Ошибка ввода", str(e))
            return
        self.refresh_table()
        last = str(len(self.db) - 1)
        self.tree.selection_set(last)
        self.tree.see(last)
        self.clear_fields()

    def goto_record(self):
        if not len(self.db):
            messagebox.showinfo("БД пуста", "В БД нет записей.")
            return
        n = simpledialog.askinteger("Перейти к записи",
                                    f"Номер записи (1 – {len(self.db)}):",
                                    minvalue=1, maxvalue=len(self.db))
        if n is None:
            return
        if str(n - 1) not in self.tree.get_children():
            self.refresh_table()            
        iid = str(n - 1)
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)

    def edit_record(self):
        i = self.selected_index()
        if i is None:
            return
        try:
            self.db.update(i, self.read_fields())
        except ValidationError as e:
            messagebox.showerror("Ошибка ввода", str(e))
            return
        self.refresh_table(self.shown)
        self.tree.selection_set(str(i))

    def delete_record(self):
        i = self.selected_index()
        if i is None:
            return
        if messagebox.askyesno("Удаление", f"Удалить запись №{i + 1}?"):
            self.db.delete(i)
            self.clear_fields()
            self.refresh_table()

    def search(self):
        criteria = self.read_fields()
        if not any(v.strip() for v in criteria.values()):
            messagebox.showinfo("Поиск", "Заполните хотя бы одно поле для поиска.")
            return
        found = self.db.search(criteria)
        self.refresh_table(found)
        self.status.set(f"Найдено записей: {len(found)} из {len(self.db)}")

    def live_search(self, _event=None):
        """Поиск при вводе: после каждой буквы таблица сразу сужается до
        подходящих записей. Если выбрана строка таблицы, поля заняты
        редактированием этой записи, и таблицу не фильтруем."""
        if self.tree.selection():
            return
        criteria = self.read_fields()
        if not any(v.strip() for v in criteria.values()):
            self.refresh_table()                 # поля пусты - показать всё
            return
        found = self.db.search(criteria, lenient=True)
        self.refresh_table(found)
        self.status.set(f"Найдено записей: {len(found)} из {len(self.db)}")

    def clear_db(self):
        if len(self.db) and messagebox.askyesno("Очистка", "Удалить ВСЕ записи из БД (в том числе с диска)?"):
            self.db.clear()
            self.clear_fields()
            self.refresh_table()
            self.set_result("")
            self.chart_data = None
            self.draw_chart()

    #вычисления
    def set_result(self, text):
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    def calculate(self):
        res = compute_all(self.db.get_all())
        if res is None:
            messagebox.showinfo("Вычисления", "БД пуста - нечего обрабатывать.")
            return
        money = lambda v: f"{v:,.2f}".replace(",", " ")
        lines = ["ГОДОВОЙ ВЫПУСК (по заводам, все виды продукции вместе)", ""]
        lines += [f"В натуральном исчислении, шт.:",
                  f"  минимум: {res['natural_min'][0]} — {money(res['natural_min'][1])}",
                  f"  максимум: {res['natural_max'][0]} — {money(res['natural_max'][1])}",
                  "В стоимостном исчислении, руб.:",
                  f"  минимум: {res['value_min'][0]} — {money(res['value_min'][1])}",
                  f"  максимум: {res['value_max'][0]} — {money(res['value_max'][1])}",
                  "", "РАСПРЕДЕЛЕНИЕ ЗАВОДОВ ПО РЕНТАБЕЛЬНОСТИ", ""]
        for label, members in res["distribution"]:
            names = ", ".join(f"{n} ({r:.1f}%)" for n, r in members) or "—"
            lines.append(f"{label}: {len(members)} шт.")
            lines.append(f"    {names}")
        lines += ["", "СВОДНАЯ ТАБЛИЦА ПО ЗАВОДАМ", ""]
        lines.append(f"{'Завод':<22}{'Выпуск, шт.':>14}{'Выпуск, руб.':>18}{'Рентаб., %':>12}")
        for n, p in sorted(res["plants"].items()):
            lines.append(f"{n:<22}{p['natural']:>14,.0f}{p['value']:>18,.0f}"
                         f"{p['profitability']:>12.1f}")
        self.set_result("\n".join(lines))
        self.chart_data = res["distribution"]
        self.draw_chart()

    #график
    def draw_chart(self):
        """Гистограмма: сколько заводов попало в каждый интервал рентабельности."""
        c = self.canvas
        c.delete("all")
        if not self.chart_data:
            c.create_text(c.winfo_width() / 2, c.winfo_height() / 2,
                          text="Нажмите «Вычислить значения»", fill="gray")
            return
        w, h = c.winfo_width(), c.winfo_height()
        left, right, top, bottom = 30, 10, 20, 50
        counts = [len(m) for _, m in self.chart_data]
        mx = max(max(counts), 1)
        n = len(counts)
        slot = (w - left - right) / n
        c.create_line(left, top, left, h - bottom)
        c.create_line(left, h - bottom, w - right, h - bottom)
        for i, ((label, _), cnt) in enumerate(zip(self.chart_data, counts)):
            x0 = left + i * slot + slot * 0.15
            x1 = left + (i + 1) * slot - slot * 0.15
            y1 = h - bottom
            y0 = y1 - (y1 - top) * cnt / mx
            c.create_rectangle(x0, y0, x1, y1, fill="#4a90d9", outline="")
            c.create_text((x0 + x1) / 2, y0 - 8, text=str(cnt))
            c.create_text((x0 + x1) / 2, y1 + 18, text=label, width=slot - 4,
                          font=("Arial", 8))


if __name__ == "__main__":
    App().mainloop()
