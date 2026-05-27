import os
import tempfile
import unittest

os.environ["ART_DATA_DIR"] = tempfile.mkdtemp(prefix="art-test-")
os.environ["ART_IMAGE_DIR"] = tempfile.mkdtemp(prefix="art-img-")

import server


class CoreTests(unittest.TestCase):
    def setUp(self):
        server.init_db()
        with server.db() as conn:
            conn.execute("DELETE FROM providers")
            conn.execute(
                """INSERT INTO providers(name,base_url,api_key_enc,models_json,default_model,priority,is_default,active,supports_reference,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    "Test Provider",
                    "mock://local",
                    server.xor_crypt(""),
                    '[{"id": "mock-vision-xl", "name": "Vision XL Mock", "enabled": true, "supports_reference": true}]',
                    "mock-vision-xl",
                    1,
                    1,
                    1,
                    1,
                    server.now_iso(),
                ),
            )

    def test_generation_payload_defaults_and_negative_prompt(self):
        payload = server.build_generation_payload({"prompt": "a ceramic lamp", "negative_prompt": "blur", "style": "product", "ratio": "4:5"})
        self.assertIn("product hero image", payload["prompt"])
        self.assertIn("--no blur", payload["prompt"])
        self.assertEqual(payload["negative_prompt"], "blur")
        self.assertEqual(payload["quality"], "standard")
        self.assertEqual(payload["size"], "1024x1280")

    def test_empty_prompt_rejected(self):
        with self.assertRaises(ValueError):
            server.build_generation_payload({"prompt": "   "})

    def test_provider_model_parser(self):
        models = server.parse_models_response({"data": [{"id": "a"}, "b", {"id": "a", "name": "dup"}]})
        self.assertEqual([m["id"] for m in models], ["a", "b"])
        self.assertFalse(models[0]["enabled"])

    def test_normalize_provider_models_filters_empty_and_dedupes(self):
        models = server.normalize_provider_models([
            {"id": "gpt-image-1", "name": "GPT Image", "enabled": True, "supports_reference": True},
            {"id": "gpt-image-1", "name": "Duplicate", "enabled": False},
            {"name": "named-only", "enabled": True},
            {"id": "   "},
            "raw-model",
        ])
        self.assertEqual([m["id"] for m in models], ["gpt-image-1", "named-only", "raw-model"])
        self.assertTrue(models[0]["enabled"])
        self.assertTrue(models[0]["supports_reference"])

    def test_provider_selection_and_reference_capability(self):
        with server.db() as conn:
            rows = conn.execute("SELECT * FROM providers").fetchall()
        self.assertTrue(server.provider_supports_model(rows[0], "mock-vision-xl", True))
        self.assertEqual(server.select_providers("mock-vision-xl", True)[0]["name"], "Test Provider")
        self.assertEqual(server.select_providers("missing-model"), [])
        self.assertEqual(server.default_model(True), "mock-vision-xl")

    def test_access_quota_validation(self):
        with server.db() as conn:
            cur = conn.execute(
                "INSERT INTO access_codes(code,total_quota,used_quota,created_at) VALUES('T',1,1,?)",
                (server.now_iso(),),
            )
            code_id = cur.lastrowid
        row, err = server.validate_access(code_id)
        self.assertIsNone(row)
        self.assertIn("额度", err)

    def test_init_db_does_not_create_default_provider(self):
        with server.db() as conn:
            conn.execute("DELETE FROM providers")
        server.init_db()
        with server.db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
