"""[火花] 占位符解析测试。"""

import unittest

from backend.app.services.execution_service import SPARK_STICKER_TOKEN, split_spark_content


class SplitSparkContentTests(unittest.TestCase):
    def test_pure_text_has_single_text_segment(self):
        self.assertEqual(split_spark_content("今日火花+1"), [("text", "今日火花+1")])

    def test_pure_token_is_single_spark_segment(self):
        self.assertEqual(split_spark_content(SPARK_STICKER_TOKEN), [("spark", "")])

    def test_mixed_text_and_token(self):
        self.assertEqual(
            split_spark_content("早呀 [火花] 记得续上"),
            [("text", "早呀 "), ("spark", ""), ("text", " 记得续上")],
        )

    def test_adjacent_tokens(self):
        self.assertEqual(
            split_spark_content("[火花][火花]"),
            [("spark", ""), ("spark", "")],
        )

    def test_empty_content_returns_no_segments(self):
        self.assertEqual(split_spark_content(""), [])
        self.assertEqual(split_spark_content(None), [])

    def test_text_around_multiple_tokens(self):
        segments = split_spark_content("a[火花]b[火花]c")
        self.assertEqual(
            segments,
            [
                ("text", "a"),
                ("spark", ""),
                ("text", "b"),
                ("spark", ""),
                ("text", "c"),
            ],
        )

    def test_sticker_type_resolves_to_spark_token(self):
        from types import SimpleNamespace

        from backend.app.models import MessageType
        from backend.app.services.dispatch_service import _resolve_message_content

        friend = SimpleNamespace(
            message=SimpleNamespace(
                message_type=MessageType.sticker,
                message_content="",
            )
        )
        self.assertEqual(_resolve_message_content(friend), SPARK_STICKER_TOKEN)


    def test_normalize_friend_name(self):
        from backend.app.services.execution_service import normalize_friend_name

        self.assertEqual(normalize_friend_name("张三 (同事) 🔥"), "张三")
        self.assertEqual(normalize_friend_name("  李四_123 【朋友】 "), "李四123")
        self.assertEqual(normalize_friend_name("Alice ✨ Spark"), "alicespark")
        self.assertEqual(normalize_friend_name(""), "")
        self.assertEqual(normalize_friend_name(None), "")


if __name__ == "__main__":
    unittest.main()
