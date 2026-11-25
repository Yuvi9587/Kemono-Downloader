import contextlib
import os
import sqlite3
import tempfile
import unittest

from src.core.platform_database import PlatformDatabaseManager


class TestPlatformDatabaseManager(unittest.TestCase):
    """Unit tests for PlatformDatabaseManager identifier quoting and compatibility."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.appdata_dir = self.temp_dir.name
        PlatformDatabaseManager._instances.clear()

    def tearDown(self):
        for instance in list(PlatformDatabaseManager._instances.values()):
            try:
                instance.conn.close()
            except Exception:
                pass
        PlatformDatabaseManager._instances.clear()
        self.temp_dir.cleanup()

    def _get_db(self, platform="kemono"):
        return PlatformDatabaseManager.get_instance(platform, self.appdata_dir)

    def _table_exists(self, db, table_name):
        db.cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
        return db.cursor.fetchone() is not None

    def test_quote_identifier(self):
        self.assertEqual(PlatformDatabaseManager.quote_identifier("in"), '"in"')
        self.assertEqual(PlatformDatabaseManager.quote_identifier("table (1)"), '"table (1)"')
        self.assertEqual(PlatformDatabaseManager.quote_identifier('bad"name'), '"bad""name"')

    def test_sanitize_name_edge_cases(self):
        db = self._get_db()

        # Empty / falsy / whitespace
        self.assertEqual(db._sanitize_name(""), "unknown_creator")
        self.assertEqual(db._sanitize_name(None), "unknown_creator")
        self.assertEqual(db._sanitize_name("   "), "creator")

        # Symbols / brackets only
        self.assertEqual(db._sanitize_name("()"), "creator")
        self.assertEqual(db._sanitize_name("[]"), "creator")
        self.assertEqual(db._sanitize_name("( ) [ ] ---"), "creator")

        # Leading digits
        self.assertEqual(db._sanitize_name("123"), "c_123")
        self.assertEqual(db._sanitize_name("42_artist"), "c_42_artist")
        self.assertEqual(db._sanitize_name("_99"), "c_99")

        # SQL reserved keywords (preserve backward-compatible sanitized names)
        for keyword in ("in", "order", "group", "select", "table", "index"):
            self.assertEqual(db._sanitize_name(keyword), keyword)
        self.assertEqual(db._sanitize_name("(in)"), "in")
        self.assertEqual(db._sanitize_name("[order]"), "order")

        # SQLite reserved sqlite_ prefix
        self.assertEqual(db._sanitize_name("sqlite_master"), "c_sqlite_master")
        self.assertEqual(db._sanitize_name("sqlite_sequence"), "c_sqlite_sequence")
        self.assertEqual(db._sanitize_name("SQLITE_USER"), "c_sqlite_user")
        self.assertEqual(db._sanitize_name("_sqlite_temp"), "c_sqlite_temp")

    def test_crud_with_reserved_words_brackets_and_sqlite_prefix(self):
        cases = [
            ("in", "id_in"),
            ("(in)", "id_paren_in"),
            ("[order]", "id_order"),
            ("select", "id_select"),
            ("table (1)", "id_table_1"),
            ("sqlite_user", "id_sqlite_user"),
        ]

        for idx, (creator_name, creator_id) in enumerate(cases):
            with self.subTest(creator_name=creator_name):
                db = self._get_db(platform=f"plat_{idx}")
                table_name = db.ensure_creator_table(creator_name, creator_id=creator_id, service="patreon")
                self.assertTrue(self._table_exists(db, table_name))

                file_hash = f"hash_{idx}"
                db.record_download(
                    creator_name=creator_name,
                    file_hash=file_hash,
                    phash=None,
                    post_id=f"post_{idx}",
                    original_filename="art.png",
                    saved_filename="art.png",
                    creator_id=creator_id,
                    service="patreon",
                    saved_path=f"/tmp/{creator_name}/art.png",
                )

                self.assertTrue(db.is_file_downloaded(creator_id, file_hash))
                self.assertFalse(db.is_file_downloaded(creator_id, "missing_hash"))

                # Also verify quoted repair-style SELECT / UPDATE / DELETE work on this table
                quoted = PlatformDatabaseManager.quote_identifier(table_name)
                db.cursor.execute(
                    f"SELECT hash, original_filename, saved_filename, saved_path FROM {quoted}"
                )
                rows = db.cursor.fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][0], file_hash)

                db.cursor.execute(
                    f"UPDATE {quoted} SET saved_path = ? WHERE hash = ?",
                    ("/new/path/art.png", file_hash),
                )
                db.cursor.execute(f"DELETE FROM {quoted} WHERE hash = ?", (file_hash,))
                db.conn.commit()
                self.assertFalse(db.is_file_downloaded(creator_id, file_hash))

                self.assertTrue(db.delete_creator(creator_id))
                self.assertFalse(self._table_exists(db, table_name))
                self.assertFalse(db.delete_creator(creator_id))

    def test_migration_from_reserved_word_old_table_to_new_table(self):
        db = self._get_db("kemono_mig_1")
        creator_id = "9001"
        service = "fanbox"

        # Creator originally recorded under reserved keyword table "in"
        old_table = db.ensure_creator_table("in", creator_id=creator_id, service=service)
        self.assertEqual(old_table, "in")
        db.toggle_sync_status(creator_id, True)
        db.update_sync_settings(creator_id, service, '{"output_dir": "D:/dl"}')
        db.record_download(
            creator_name="in",
            file_hash="old_hash_1",
            phash=None,
            post_id="1",
            original_filename="old.png",
            saved_filename="old.png",
            creator_id=creator_id,
            service=service,
            saved_path="D:/dl/old.png",
        )

        # Rename creator to a normal name -> triggers old_table_name ("in") -> new_table migration
        new_table = db.ensure_creator_table("Renamed Creator", creator_id=creator_id, service=service)
        self.assertEqual(new_table, "renamed_creator")
        self.assertFalse(self._table_exists(db, "in"))
        self.assertTrue(self._table_exists(db, "renamed_creator"))
        self.assertTrue(db.is_file_downloaded(creator_id, "old_hash_1"))

        creators = db.get_all_creators()
        self.assertEqual(len(creators), 1)
        self.assertEqual(creators[0]["sanitized_table_name"], "renamed_creator")
        self.assertEqual(creators[0]["is_synced"], 1)
        self.assertEqual(creators[0]["sync_settings"], '{"output_dir": "D:/dl"}')

    def test_migration_from_old_table_to_reserved_word_new_table(self):
        db = self._get_db("kemono_mig_2")
        creator_id = "9002"
        service = "patreon"

        db.record_download(
            creator_name="Old Name",
            file_hash="legacy_hash_2",
            phash=None,
            post_id="2",
            original_filename="img.jpg",
            saved_filename="img.jpg",
            creator_id=creator_id,
            service=service,
            saved_path="D:/dl/img.jpg",
        )
        self.assertTrue(self._table_exists(db, "old_name"))

        # Migrate into reserved keyword table "in"
        new_table = db.ensure_creator_table("(in)", creator_id=creator_id, service=service)
        self.assertEqual(new_table, "in")
        self.assertFalse(self._table_exists(db, "old_name"))
        self.assertTrue(self._table_exists(db, "in"))
        self.assertTrue(db.is_file_downloaded(creator_id, "legacy_hash_2"))

    def test_backward_compatibility_with_legacy_existing_database(self):
        db_dir = os.path.join(self.appdata_dir, "databases")
        os.makedirs(db_dir, exist_ok=True)
        legacy_db_path = os.path.join(db_dir, "legacy.db")

        # Simulate an older schema database before service/is_synced/sync_settings/saved_path existed
        with contextlib.closing(sqlite3.connect(legacy_db_path)) as conn:
            with conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    CREATE TABLE creator_mappings (
                        original_name TEXT,
                        sanitized_table_name TEXT PRIMARY KEY,
                        creator_id TEXT
                    )
                    """
                )
                cur.execute(
                    "INSERT INTO creator_mappings (original_name, sanitized_table_name, creator_id) VALUES (?, ?, ?)",
                    ("Existing Artist", "existing_artist", "777"),
                )
                cur.execute(
                    """
                    CREATE TABLE existing_artist (
                        hash TEXT,
                        phash TEXT,
                        post_id TEXT,
                        original_filename TEXT,
                        saved_filename TEXT,
                        creator_id TEXT
                    )
                    """
                )
                cur.execute(
                    "INSERT INTO existing_artist VALUES (?, ?, ?, ?, ?, ?)",
                    ("legacy_hash_777", None, "10", "first.png", "first.png", "777"),
                )

        db = self._get_db("legacy")
        self.assertTrue(db.is_file_downloaded("777", "legacy_hash_777"))

        # Recording a new download reuses existing_artist and safely migrates saved_path column
        db.record_download(
            creator_name="Existing Artist",
            file_hash="new_hash_777",
            phash=None,
            post_id="11",
            original_filename="second.png",
            saved_filename="second.png",
            creator_id="777",
            service="patreon",
            saved_path="D:/dl/second.png",
        )

        self.assertTrue(db.is_file_downloaded("777", "legacy_hash_777"))
        self.assertTrue(db.is_file_downloaded("777", "new_hash_777"))

        db.cursor.execute('SELECT hash, saved_path FROM "existing_artist" ORDER BY post_id')
        rows = db.cursor.fetchall()
        self.assertEqual(
            rows,
            [
                ("legacy_hash_777", None),
                ("new_hash_777", "D:/dl/second.png"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
