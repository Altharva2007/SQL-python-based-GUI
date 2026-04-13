#!/usr/bin/env python3
import pathlib
import sys
import datetime
import os
import tkinter as tk
from tkinter import ttk, messagebox
import oracledb
from dotenv import load_dotenv

# Load environment variables from .env file for security
load_dotenv()

# Database credentials retrieved from environment variables
DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST     = os.getenv("DB_HOST", "coeoracle.aus.edu")
DB_PORT     = os.getenv("DB_PORT", "1521")
DB_SERVICE  = os.getenv("DB_SERVICE", "orcl")

def coerce(value, ora_type):
    """
    Coerces raw string values from Entry widgets into appropriate Python/Oracle data types.
    """
    if value == "" or value is None:
        return None
    t = ora_type.upper()
    if t.startswith("NUMBER"):
        try:
            return int(value) if "." not in value else float(value)
        except ValueError:
            raise ValueError("Enter a valid numeric value.")
    if t.startswith(("DATE", "TIMESTAMP")):
        try:
            return datetime.datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Enter date in YYYY-MM-DD format.")
    return value

class OracleGUIApp(tk.Tk):
    def __init__(self, pool):
        super().__init__()
        self.title("Car Dealership Manager - Enterprise Edition v1.0")
        self.geometry("900x700")

        self.pool = pool  # Database connection pool
        self.table_meta = []  # Stores (column_name, data_type, nullable)
        self.entries = {}     # Stores Entry widgets mapped by column name
        self.pk_cols = []     # Stores Primary Key column names
        self.selected_pk = None # Stores values of the PK for the currently selected row

        self.make_main_screen()

    def get_conn(self):
        """Acquires a connection from the Oracle connection pool."""
        return self.pool.acquire()

    def release_conn(self, conn):
        """Releases the connection back to the pool."""
        self.pool.release(conn)

    def make_main_screen(self):
        """Initializes the main GUI layout with a sidebar and a content area."""
        container = ttk.PanedWindow(self, orient="horizontal")
        container.pack(fill="both", expand=True)

        # Left Panel: Table Explorer
        left = ttk.Frame(container, padding=10)
        self.tables_tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.tables_tree.pack(fill="both", expand=True)
        self.tables_tree.bind("<<TreeviewSelect>>", self._on_table_select)
        self.populate_tables()
        container.add(left, weight=1)

        # Right Panel: Dynamic Form and Data Grid
        self.right = ttk.Frame(container, padding=10)
        container.add(self.right, weight=4)

    def _on_table_select(self, event):
        """Handles table selection from the sidebar."""
        sel = self.tables_tree.selection()
        if sel:
            table_name = self.tables_tree.item(sel)["text"]
            self.load_table(table_name)

    def populate_tables(self):
        """Fetches all user tables and populates the sidebar treeview."""
        conn = self.get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT table_name FROM user_tables ORDER BY table_name")
            for (tbl,) in cur:
                self.tables_tree.insert("", "end", text=tbl)
        finally:
            self.release_conn(conn)

    def load_table(self, table_name):
        """Loads metadata and data for the selected table and refreshes UI."""
        for child in self.right.winfo_children():
            child.destroy()

        conn = self.get_conn()
        try:
            cur = conn.cursor()
            # Fetch Column Metadata: Name, Type, and Nullability
            cur.execute("""
                SELECT column_name, data_type, nullable 
                FROM user_tab_columns 
                WHERE table_name = :tbl 
                ORDER BY column_id
            """, tbl=table_name.upper())
            self.table_meta = cur.fetchall()

            # Fetch Primary Key Metadata to handle Updates and Deletes safely
            cur.execute("""
                SELECT cols.column_name FROM user_constraints cons
                JOIN user_cons_columns cols ON cons.constraint_name = cols.constraint_name
                WHERE cons.table_name = :tbl AND cons.constraint_type = 'P' 
                ORDER BY cols.position
            """, tbl=table_name.upper())
            self.pk_cols = [r[0] for r in cur]
        finally:
            self.release_conn(conn)

        self._render_ui_elements(table_name)

    def _render_ui_elements(self, table_name):
        """Renders the dynamic input form and the data grid."""
        # Form Section
        frm = ttk.LabelFrame(self.right, text=f"Record Management: {table_name}")
        frm.pack(side="top", fill="x", padx=5, pady=5)

        self.entries.clear()
        for r, (col, dtype, nullable) in enumerate(self.table_meta):
            ttk.Label(frm, text=f"{col} ({dtype})").grid(row=r, column=0, sticky="e", padx=5, pady=2)
            ent = ttk.Entry(frm, width=35)
            ent.grid(row=r, column=1, sticky="w", padx=5, pady=2)
            self.entries[col] = ent

        # CRUD Action Buttons
        btn_frm = ttk.Frame(frm)
        btn_frm.grid(row=len(self.table_meta), column=0, columnspan=2, pady=10)
        ttk.Button(btn_frm, text="Insert", command=lambda: self.insert_row(table_name)).pack(side="left", padx=5)
        ttk.Button(btn_frm, text="Save Update", command=lambda: self.update_row(table_name)).pack(side="left", padx=5)
        ttk.Button(btn_frm, text="Delete", command=lambda: self.delete_row(table_name)).pack(side="left", padx=5)
        ttk.Button(btn_frm, text="Clear", command=self.clear_form).pack(side="left", padx=5)

        # Data Grid (Treeview)
        self.grid = ttk.Treeview(self.right, show="headings", selectmode="browse")
        self.grid["columns"] = [col for col, *_ in self.table_meta]
        self.grid.pack(side="bottom", fill="both", expand=True)

        for col, *_ in self.table_meta:
            self.grid.heading(col, text=col)
            self.grid.column(col, width=100, anchor="center")

        self.grid.bind("<<TreeviewSelect>>", self.on_row_select)
        self.reload_grid(table_name)

    def values_from_entries(self):
        """Collects and validates input data from the form entries."""
        vals = {}
        for col, dtype, nullable in self.table_meta:
            raw = self.entries[col].get()
            if nullable == "N" and raw == "":
                raise ValueError(f"Mandatory field '{col}' is missing.")
            vals[col] = coerce(raw, dtype)
        return vals

    def insert_row(self, table):
        """Executes a dynamic INSERT SQL statement."""
        try:
            vals = self.values_from_entries()
            cols = ", ".join(vals.keys())
            binds = ", ".join([f":{i+1}" for i in range(len(vals))])
            sql = f"INSERT INTO {table} ({cols}) VALUES ({binds})"
            
            conn = self.get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, list(vals.values()))
                    conn.commit()
                messagebox.showinfo("Success", "New record inserted successfully.")
                self.reload_grid(table)
                self.clear_form()
            finally:
                self.release_conn(conn)
        except Exception as e:
            messagebox.showerror("Database Error", str(e))

    def update_row(self, table):
        """Executes a dynamic UPDATE SQL statement using Primary Keys."""
        if not self.selected_pk:
            messagebox.showwarning("Selection Required", "Please select a row from the grid first.")
            return
        try:
            vals = self.values_from_entries()
            sets = ", ".join([f"{c}=:{i+1}" for i, c in enumerate(vals)])
            where = " AND ".join([f"{pk}=:{len(vals)+i+1}" for i, pk in enumerate(self.pk_cols)])
            sql = f"UPDATE {table} SET {sets} WHERE {where}"

            conn = self.get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, list(vals.values()) + list(self.selected_pk))
                    conn.commit()
                messagebox.showinfo("Success", "Record updated successfully.")
                self.reload_grid(table)
            finally:
                self.release_conn(conn)
        except Exception as e:
            messagebox.showerror("Update Error", str(e))

    def delete_row(self, table):
        """Executes a dynamic DELETE SQL statement."""
        if not self.selected_pk:
            messagebox.showwarning("Selection Required", "Please select a row to delete.")
            return
        if not messagebox.askyesno("Confirm Deletion", "Are you sure you want to permanently delete this record?"):
            return
        
        where = " AND ".join([f"{pk}=:{i+1}" for i, pk in enumerate(self.pk_cols)])
        sql = f"DELETE FROM {table} WHERE {where}"

        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, self.selected_pk)
                conn.commit()
            messagebox.showinfo("Success", "Record deleted successfully.")
            self.reload_grid(table)
            self.clear_form()
        finally:
            self.release_conn(conn)

    def reload_grid(self, table):
        """Refreshes the data grid with the latest records from the database."""
        for row in self.grid.get_children():
            self.grid.delete(row)
        conn = self.get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM {table}")
            for rec in cur:
                self.grid.insert("", "end", values=list(rec))
        finally:
            self.release_conn(conn)

    def clear_form(self):
        """Clears all input fields in the current form."""
        for e in self.entries.values():
            e.delete(0, "end")
        self.selected_pk = None

    def on_row_select(self, event):
        """Populates the form when a row is selected in the data grid."""
        sel = self.grid.selection()
        if not sel: return
        values = self.grid.item(sel)["values"]
        
        # Fill entries with grid values
        for (col, *_), val in zip(self.table_meta, values):
            self.entries[col].delete(0, "end")
            self.entries[col].insert(0, val if val is not None and str(val) != "None" else "")
        
        # Determine the Primary Key values for the selected row for future UPDATE/DELETE
        col_names = [c[0] for c in self.table_meta]
        self.selected_pk = tuple(values[col_names.index(pk)] for pk in self.pk_cols)

if __name__ == "__main__":
    # Main entry point: Initialize the connection pool and launch the application
    try:
        dsn_str = f"{DB_HOST}:{DB_PORT}/{DB_SERVICE}"
        # Create a persistent pool for improved performance and resource handling
        connection_pool = oracledb.create_pool(
            user=DB_USER, 
            password=DB_PASSWORD, 
            dsn=dsn_str,
            min=1, 
            max=5, 
            increment=1
        )
        app = OracleGUIApp(connection_pool)
        app.mainloop()
    except Exception as e:
        print(f"FAILED TO START APPLICATION: {e}")