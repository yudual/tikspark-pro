"""[火花] 占位符解析测试。"""

import unittest
from unittest.mock import patch

from backend.app.services.execution_service import (
    SPARK_STICKER_TOKEN,
    ExecutionService,
    split_spark_content,
    target_identity_matches_text,
)


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


    def test_target_identity_match_is_strict_enough_for_send_guard(self):
        self.assertTrue(target_identity_matches_text("Serendipity^", "Serendipity^", "nimingzhe114"))
        self.assertTrue(target_identity_matches_text("抖音号：nimingzhe114", "Serendipity^", "nimingzhe114"))
        self.assertFalse(target_identity_matches_text("当前会话：其他好友", "Serendipity^", "nimingzhe114"))
        self.assertFalse(target_identity_matches_text("S", "Serendipity^", "nimingzhe114"))

    def test_mixed_content_flushes_each_text_chunk_once(self):
        service = ExecutionService()
        send_receipt = {}

        with (
            patch.object(
                service,
                "_flush_text_message",
                side_effect=[(True, ""), (True, "")],
            ) as flush_text,
            patch.object(
                service,
                "_send_spark_sticker",
                return_value=(True, "ok", False),
            ) as send_spark,
            patch("backend.app.services.execution_service.time.sleep"),
        ):
            result = service._send_content_segments(
                object(),
                object(),
                "早呀 [火花] 记得续上",
                send_receipt,
            )

        self.assertEqual(result, (True, "", 1, False))
        self.assertEqual(
            [call.args[2] for call in flush_text.call_args_list],
            ["早呀 ", " 记得续上"],
        )
        send_spark.assert_called_once()


if __name__ == "__main__":
    unittest.main()
