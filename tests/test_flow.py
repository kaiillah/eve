"""Standard-library checks; application imports and hardware are never executed."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "legacy/single_script_fall_back.py"
FLOW = ROOT / "eve_main/flow.py"


def functions(path):
    return {
        node.name: node
        for node in ast.parse(path.read_bytes()).body
        if isinstance(node, ast.FunctionDef)
    }


class SourceChecks(unittest.TestCase):
    def test_application_compiles(self):
        paths = [LEGACY, *sorted((ROOT / "eve_main").glob("*.py"))]
        self.assertEqual(len(paths), 9)
        for path in paths:
            with self.subTest(path=path.name):
                compile(path.read_bytes(), str(path), "exec")



class ConversationChecks(unittest.TestCase):
    def run_chat(self, path, cycles, user_id=7):
        clock = SimpleNamespace(now=0)
        pending = iter(cycles)
        current = {}
        prompts, spoken, saved = [], [], []

        def listen(seconds):
            current.update(next(pending))  # Unexpected extra listening fails the test.
            clock.now += 10
            return current["voice"]

        def respond(prompt, history):
            prompts.append(prompt)
            return "reply:" + prompt

        namespace = dict(
            time=SimpleNamespace(time=lambda: clock.now),
            PRESENCE_KEEP_ALIVE=3.0, LISTEN_SECONDS=5.0, KEEPALIVE_MARGIN=2.0,
            ROBOT_NAME="Test Robot",
            listen_once=listen, input=lambda _: current.get("typed", ""),
            print=lambda *args: None, get_ollama_response=respond,
            speak=spoken.append,
            save_conversation_history=lambda uid, history: saved.append(uid),
            user_present_now=lambda *args: current["present"],
        )
        # Execute only the selected function and actual goodbye helpers.
        config = ast.parse((ROOT / "eve_main/config.py").read_bytes())
        namespace["GOODBYE_KEYWORDS"] = next(
            ast.literal_eval(node.value) for node in config.body
            if isinstance(node, ast.Assign)
            and node.targets[0].id == "GOODBYE_KEYWORDS"
        )
        import re
        namespace["re"] = re
        nodes = list(functions(ROOT / "eve_main/utils.py").values())
        nodes.append(functions(path)["conduct_chat"])
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
        namespace["conduct_chat"](None, None, "Visitor", user_id, [])
        return prompts, spoken, saved

    def test_silence_and_departure(self):
        for path in (LEGACY, FLOW):
            with self.subTest(version=str(path)):
                prompts, spoken, saved = self.run_chat(path, [dict(voice="", present=False)])
                self.assertEqual(len(prompts), 1)
                self.assertIn("walked away", prompts[0])
                self.assertEqual(spoken, ["reply:" + prompts[0]])
                self.assertEqual(saved, [7])

    def test_silence_while_present_then_goodbye(self):
        for path in (LEGACY, FLOW):
            with self.subTest(version=str(path)):
                prompts, spoken, saved = self.run_chat(path, [
                    dict(voice="", present=True), dict(voice="bye", present=True),
                ])
                self.assertEqual(len(prompts), 1)
                self.assertIn("They are leaving now", prompts[0])
                self.assertEqual(saved, [7])
                self.assertEqual(len(spoken), 1)

    def test_spoken_and_typed_replies_then_departure(self):
        for path in (LEGACY, FLOW):
            for typed in (False, True):
                for user_id in (None, 7):
                    with self.subTest(version=str(path), typed=typed, user_id=user_id):
                        prompts, spoken, saved = self.run_chat(path, [
                            dict(voice="" if typed else "hello Eve", typed="hello Eve", present=True),
                            dict(voice="", typed="", present=False),
                        ], user_id)
                        self.assertEqual(len(prompts), 2)
                        self.assertEqual(prompts[0], "hello Eve")
                        self.assertIn("walked away", prompts[1])
                        self.assertEqual(spoken, ["reply:" + p for p in prompts])
                        self.assertEqual(saved, [7, 7] if user_id else [])


if __name__ == "__main__":
    unittest.main()
