#!/usr/bin/env python3

import pathlib
import sqlite3
import sys
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

# Safe import for Oracle
try:
    import oracledb as cx_Oracle
    ORACLE_AVAILABLE = True
except ImportError:
    ORACLE_AVAILABLE = False

# --- Database Credentials (Oracle) ---
DB_USER     = "b00089586"
DB_PASSWORD = "b00089586"
DB_HOST     = "coeoracle.aus.edu"         
DB_PORT     = 1521
DB_SERVICE  = "orcl"                

def make_dsn(host, port, service):
    if ORACLE_AVAILABLE:
        return cx_Oracle.makedsn(host, port, service_name=service)
    return None

def coerce(value, ora_type):
    if value == "" or value is None:
        return None
    t = str(ora_type).upper()
    if t.startswith("NUMBER") or t.startswith("INT"):
        try:
            return int(value) if "." not in str(value) else float(value)
        except ValueError:
            raise ValueError("Enter a valid number.")
    if t.startswith(("DATE", "TIMESTAMP")):
        try:
            return datetime.datetime.strptime(str(value), "%Y-%m-%d")
        except ValueError:
            raise ValueError("Enter date as YYYY-MM-DD.")
    return value

class oracleGUIapp(tk.Tk):
    def __init__(self, connection):
        super().__init__()
        self.title("Car Dealership Manager (Multi-DB Support)")
        self.geometry("800x520")

        self.conn = connection
        self.is_sqlite = isinstance(connection, sqlite3.Connection)
        self.table_meta = []
        self.entries = {}
        self.pk_cols = []
        self.selected_pk = None

        self.make_main_screen()

    def make_main_screen(self):
        container = ttk.PanedWindow(self, orient="horizontal")
        container.pack(fill="both", expand=True)

        left = ttk.Frame(container, padding=10)
        self.tables_tree = ttk.Treeview(left, show="tree", selectmode="browse", height=20)
        self.tables_tree.pack(fill="y", expand=True)
        self.tables_tree.bind("<<TreeviewSelect>>",
                         lambda e: self.load_table(self.tables_tree.item(self.tables_tree.selection())["text"]))
        self.populate_tables(self.tables_tree)
        container.add(left, weight=1)

        self.right = ttk.Frame(container, padding=10)
        container.add(self.right, weight=3)

    def populate_tables(self, tree):
        for item in tree.get_children():
            tree.delete(item)
        cur = self.conn.cursor()
        if self.is_sqlite:
            query = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        else:
            query = "SELECT table_name FROM user_tables ORDER BY table_name"
        
        try:
            cur.execute(query)
            for (tbl,) in cur:
                tree.insert("", "end", text=tbl)
        except Exception as e:
            print(f"Error listing tables: {e}")

    def load_table(self, table_name):
        for child in self.right.winfo_children():
            child.destroy()

        cur = self.conn.cursor()
        if self.is_sqlite:
            # SQLite mock meta-data
            cur.execute(f"PRAGMA table_info({table_name})")
            # Convert SQLite pragma to (name, type, nullable)
            self.table_meta = [(r[1], r[2], "N" if r[3] else "Y") for r in cur.fetchall()]
            cur.execute(f"PRAGMA table_info({table_name})")
            self.pk_cols = [r[1] for r in cur.fetchall() if r[5] > 0]
        else:
            cur.execute("SELECT column_name, data_type, nullable FROM user_tab_columns WHERE table_name = :tbl ORDER BY column_id", tbl=table_name.upper())
            self.table_meta = cur.fetchall()
            cur.execute("SELECT cols.column_name FROM user_constraints cons JOIN user_cons_columns cols ON cons.constraint_name = cols.constraint_name WHERE cons.table_name = :tbl AND cons.constraint_type = 'P' ORDER BY cols.position", tbl=table_name.upper())
            self.pk_cols = [r[0] for r in cur]

        frm = ttk.LabelFrame(self.right, text=f"Table: {table_name}")
        frm.pack(side="top", fill="x", padx=5, pady=5)

        self.entries.clear()
        for r, (col, dtype, nullable) in enumerate(self.table_meta):
            ttk.Label(frm, text=f"{col}").grid(row=r, column=0, sticky="e")
            ent = ttk.Entry(frm, width=30)
            ent.grid(row=r, column=1, sticky="w", padx=5, pady=2)
            self.entries[col] = ent

        btn_row = len(self.table_meta)
        bframe = ttk.Frame(frm)
        bframe.grid(row=btn_row, column=0, columnspan=2, pady=10)
        ttk.Button(bframe, text="Insert", command=lambda: self.insert_row(table_name)).pack(side="left", padx=4)
        ttk.Button(bframe, text="Delete", command=lambda: self.delete_row(table_name)).pack(side="left", padx=4)
        ttk.Button(bframe, text="Clear", command=self.clear_form).pack(side="left", padx=4)

        self.grid = ttk.Treeview(self.right, show="headings", selectmode="browse")
        self.grid["columns"] = [col for col, *_ in self.table_meta]
        self.grid.pack(side="bottom", fill="both", expand=True)

        for col, *_ in self.table_meta:
            self.grid.heading(col, text=col)
            self.grid.column(col, width=100)

        self.grid.bind("<<TreeviewSelect>>", self.on_row_select)
        self.reload_grid(table_name)

    def reload_grid(self, table):
        for row in self.grid.get_children():
            self.grid.delete(row)
        cur = self.conn.cursor()
        cur.execute(f"SELECT * FROM {table}")
        for rec in cur:
            self.grid.insert("", "end", values=list(rec))

    def insert_row(self, table):
        vals = {col: self.entries[col].get() for col, *_ in self.table_meta}
        cols = ", ".join(vals.keys())
        placeholders = ", ".join(["?" if self.is_sqlite else f":{i+1}" for i in range(len(vals))])
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        try:
            self.conn.execute(sql, list(vals.values()))
            self.conn.commit()
            self.reload_grid(table)
            self.clear_form()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def delete_row(self, table):
        if not self.selected_pk: return
        where = " AND ".join([f"{pk}=?" if self.is_sqlite else f"{pk}=:1" for pk in self.pk_cols])
        sql = f"DELETE FROM {table} WHERE {where}"
        try:
            self.conn.execute(sql, self.selected_pk)
            self.conn.commit()
            self.reload_grid(table)
            self.clear_form()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def clear_form(self):
        for e in self.entries.values(): e.delete(0, "end")
        self.selected_pk = None

    def on_row_select(self, _):
        sel = self.grid.selection()
        if not sel: return
        values = self.grid.item(sel)["values"]
        for (col, *_), val in zip(self.table_meta, values):
            self.entries[col].delete(0, "end")
            self.entries[col].insert(0, val)
        self.selected_pk = tuple(values) # Simplified for demo

# --- Launch Logic ---
if __name__ == "__main__":
    conn = None
    # 1. Try Oracle
    if ORACLE_AVAILABLE:
        try:
            dsn = make_dsn(DB_HOST, DB_PORT, DB_SERVICE)
            conn = cx_Oracle.connect(user=DB_USER, password=DB_PASSWORD, dsn=dsn)
            print("Connected to Oracle.")
        except:
            pass

    # 2. Fallback to SQLite
    if conn is None:
        if messagebox.askyesno("Oracle Offline", "Connect to local SQLite database instead?"):
            conn = sqlite3.connect("dealership.db")
            # Create demo table
            conn.execute("CREATE TABLE IF NOT EXISTS CARS (ID INT PRIMARY KEY, BRAND TEXT, MODEL TEXT)")
            conn.commit()
            print("Connected to SQLite.")
        else:
            sys.exit()

    if conn:
        app = oracleGUIapp(conn)
        app.mainloop()
