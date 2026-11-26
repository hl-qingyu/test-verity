import unittest
from unittest.mock import Mock, patch

from app.modules.ai import task_lifecycle


class TaskLifecycleTests(unittest.TestCase):
    def test_progress_throttle_accepts_a_forced_check_and_keeps_the_callback(self):
        callback = Mock()
        check = task_lifecycle.throttled(callback, seconds=1)
        with patch.object(task_lifecycle, "monotonic", side_effect=[0, 0.25, 0.5, 1.49, 1.5]):
            check()
            check()
            check(force=True)
            check()
            check()
        self.assertEqual(callback.call_count, 3)

    def test_conversation_preserves_prior_turns_and_frozen_context_order(self):
        previous = {"role": "assistant", "content": "上一轮回答"}
        context = {"message_source": "报告", "messages": [previous]}
        messages = task_lifecycle.conversation_messages(context, "追问", "固定资料：")
        self.assertEqual(messages[0]["content"], '固定资料：{"message_source": "报告"}')
        self.assertEqual(messages[1:], [previous, {"role": "user", "content": "追问"}])
        self.assertEqual(context["messages"], [previous])
